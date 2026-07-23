"""Provider-neutral session-surface resolver service.

AS29 stage 3 (slice 3) — repaired per parent review:

Resolution rules (no exceptions — always returns a stable snapshot):

1. **Unknown provider** → unsupported snapshot.
2. **Disabled provider** → unsupported snapshot.
3. **No exact ``surface_id`` match** → unsupported snapshot.
4. **No installed-version compatibility** — select only when BOTH ``surface_id``
   AND exact installed-version compatibility match. Never select first
   matching surface by id alone. A caller version hint may narrow selection
   but cannot substitute for installed-version discovery.
5. **Blocked declaration** → unsupported snapshot.
6. **No platform match** for the target platform → unsupported snapshot.
   Platform matching is exact normalised target-triple only (e.g.
   "linux-amd64" != "linux-arm64" and "linux" does not prefix-match
   "windows-amd64").
7. **Unvalidated high-level ceiling** — after selecting platform evidence,
   enforce the validation/effective-observation ceiling against the selected
   per-platform evidence (or declaration level if no per-platform evidence
   legitimately applies). Non-validated O2+ → unsupported.
7b. **Inventory proof gate** (AS27 RV770) — a validated O1+ claim requires
    that the target platform appear in the AS27 inventory's locally-validated
    ``platform_evidence`` for this (provider_id, surface_id) pair. Descriptor
    YAML cannot bypass inventory evidence; vendor product support alone does
    not prove local observability validation.
8. **Missing adapter factory** (adapter_ref is set but cannot be resolved) →
   unsupported snapshot.

The ``resolved_version`` field on success contains the *actual installed*
provider version. Unsupported snapshots carry a stable neutral version —
diagnostic reasons are NOT encoded into version identity.

Adapter refs are resolved only to *existence* (to detect missing factories);
they are never carried into the foundation snapshot.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from audiagentic.foundation.transports.session_surface import (
    ContentChannelCapability,
    ContentStreamCapabilities,
    ControlSupport,
    EffectiveObservationLevel,
    LifecycleInstallation,
    LifecycleObservationCapabilities,
    LifecycleSource,
    PlatformEvidence,
    ResolvedSessionSurface,
    SessionControlAction,
    SessionIdentityCapabilities,
    SessionIdentityOperation,
    SessionMappingFacts,
    SessionOwnershipMode,
    SessionSurfaceRef,
    SurfaceValidation,
    SurfaceValidationState,
)

from ..contracts.session_surface import SurfaceHint
from ..descriptors.registry import get_descriptor

# ---------------------------------------------------------------------------
# Internal resolution outcome reasons (informational, not exceptions)
# ---------------------------------------------------------------------------

_UNSUPPORTED_REASONS = frozenset({
    "unknown-provider",
    "disabled-provider",
    "no-surface-id-match",
    "version-mismatch",
    "blocked-declaration",
    "unvalidated-high-level",
    "no-platform-match",
    "missing-adapter-factory",
    "no-inventory-proof",  # YAML claims O1+ but inventory lacks platform evidence
})

# ---------------------------------------------------------------------------
# Platform triple detection (Fix 3: exact normalized target triples)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Version constraint parsing (local helpers — no YAML/runtime load)
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _parse_version(version_str: str) -> tuple[int, ...] | None:
    """Parse a version string into a tuple of integers for comparison."""
    match = _VERSION_RE.match(version_str.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _version_satisfies(installed_version: str, constraint: str) -> bool | None:
    """Check whether *installed_version* satisfies *constraint*.

    Constraint format: optional operator (>= | <= | > | < | ==) followed by
    a version string, e.g. '>=1.0', '==2.3.1'. Returns True/False when the
    comparison can be evaluated; returns None if either version is unparseable
    (in which case we defer to other resolution heuristics).
    """
    installed = _parse_version(installed_version)
    if installed is None:
        return None

    constraint = constraint.strip()
    match = re.match(r"^(>=|<=|>|<|==)?\s*(.+)$", constraint)
    if not match:
        return None

    operator = match.group(1) or ">="
    required = _parse_version(match.group(2))
    if required is None:
        return None

    _OPS = {
        ">=": installed >= required,
        "<=": installed <= required,
        ">":  installed > required,
        "<":  installed < required,
        "==": installed == required,
    }
    return _OPS.get(operator, False)


# ---------------------------------------------------------------------------
# Installed-version discovery (Fix 2: probe the actual installed version)
# ---------------------------------------------------------------------------

def _probe_installed_version(
    descriptor: Any,
) -> str | None:
    """Return the actual installed provider version via the descriptor's cli_probe.

    Uses the existing ``providers/adapters/probe`` infrastructure to run the
    CLI and parse the version from stdout. Returns None when there is no
    cli_probe or the probe fails (tool not installed, unparseable output).

    Never raises — failures are silently treated as "unknown version".
    """
    cli_probe = getattr(descriptor, "cli_probe", None)
    if not cli_probe or not isinstance(cli_probe, list):
        return None

    try:
        from audiagentic.components.providers.adapters.probe import probe_cli_version

        executable_name = cli_probe[0]
        result = probe_cli_version(executable_name, cli_probe)
        if not result.get("available"):
            return None
        output = result.get("stdout", "")
        parsed = _parse_version(output)
        if parsed is not None:
            return ".".join(str(v) for v in parsed)
    except Exception:  # noqa: BLE001 — version discovery is best-effort
        pass
    return None


# ---------------------------------------------------------------------------
# Unsupported snapshot factory (Fix 5: stable neutral version, no diagnostics)
# ---------------------------------------------------------------------------

def _unsupported_snapshot(
    provider_id: str,
    surface_id: str,
    reason: str,
    *,
    requested_version: str | None = None,
) -> ResolvedSessionSurface:
    """Build an unsupported ResolvedSessionSurface.

    The ``resolved_version`` is a stable neutral value — the requested/known
    version if available, otherwise 'unknown'. Diagnostic reasons are carried
    in ``validation.state == UNSUPPORTED``, NOT encoded into version identity.
    """
    resolved_version = requested_version if requested_version else "unknown"
    ref = SessionSurfaceRef(
        provider_id=provider_id,
        surface_id=surface_id,
        resolved_version=resolved_version,
    )
    return ResolvedSessionSurface(
        ref=ref,
        identity=SessionIdentityCapabilities(),
        validation=SurfaceValidation(
            state=SurfaceValidationState.UNSUPPORTED,
            effective_level=EffectiveObservationLevel.O0,
        ),
    )


# ---------------------------------------------------------------------------
# Adapter existence check (existence-only, never leaks into snapshot)
# ---------------------------------------------------------------------------

def _adapter_factory_exists(adapter_ref: str) -> bool:
    """Check whether an adapter_ref dotpath resolves to a callable.

    Returns True only when the ref resolves without error and points to a
    callable object. The resolved object is *not* retained or returned.
    """
    try:
        from audiagentic.foundation.config.refs import resolve_ref
        obj = resolve_ref(adapter_ref)
        return callable(obj)
    except Exception:  # noqa: BLE001 — existence check only
        return False


# ---------------------------------------------------------------------------
# Effective level ceiling enforcement (Fix 4: against selected PE, not decl)
# ---------------------------------------------------------------------------

def _enforce_validation_ceiling(
    effective_level: EffectiveObservationLevel,
    validation_state: SurfaceValidationState,
) -> tuple[bool, str]:
    """Return (is_blocked, reason) when O2+ is not validated.

    A non-validated declaration with effective_level >= O2 is ceiling-blocked;
    the gateway must not treat it as providing advanced capability.
    """
    if effective_level.numeric >= 2 and validation_state not in (
        SurfaceValidationState.BLOCKED,
        SurfaceValidationState.VALIDATED,
    ):
        return True, "unvalidated-high-level"
    return False, ""


# ---------------------------------------------------------------------------
# Platform match check (Fix 3: exact normalized target triples only)
# ---------------------------------------------------------------------------

def _platform_matches(
    target_platform: str,
    platforms: tuple[PlatformEvidence, ...],
) -> PlatformEvidence | None:
    """Return the first platform evidence with an *exact* platform match.

    Only exact normalised target-triple equality is accepted (e.g.
    'linux-amd64' == 'linux-amd64'). No prefix/base matching — 'linux' does
    NOT match 'linux-amd64' and 'linux-amd64' never borrows proof from
    'windows-amd64'.
    """
    for pe in platforms:
        if pe.platform == target_platform:
            return pe
    return None


# ---------------------------------------------------------------------------
# Declaration selection (Fix 2: installed-version disambiguation)
# ---------------------------------------------------------------------------

def _select_declaration(
    declarations: tuple[Any, ...],
    surface_id: str,
    installed_version: str | None,
    version_hint: str | None,
) -> tuple[Any, str | None]:
    """Select the best matching declaration for *surface_id*.

    Selection rules:
    1. Filter by exact ``surface_id`` match.
    2. If a caller version hint is provided, narrow to declarations whose
       version_constraint matches or contains the hint (version hint prunes,
       does not substitute for installed-version discovery).
    3. Check installed-version compatibility: select only declarations whose
       version_constraint is satisfied by the actual installed version.
    4. Among remaining candidates, prefer the most specific constraint
       (highest minimum version that is still satisfied).

    Returns (declaration, requested_version) on success or (None, reason) on
    failure. The *requested_version* is the hint's version_hint if set, else
    None — used for stable unsupported snapshot construction.
    """
    # Step 1: filter by surface_id
    matching = [d for d in declarations if d.surface_id == surface_id]
    if not matching:
        return None, "no-surface-id-match"

    requested_version = version_hint

    # Step 2: narrow by caller version hint (if provided)
    if version_hint is not None:
        narrowed = [d for d in matching if d.version_constraint == version_hint]
        if narrowed:
            matching = narrowed

    # Step 3: installed-version compatibility check
    if installed_version is not None and len(matching) > 1:
        # Multiple declarations with same surface_id — disambiguate by
        # installed-version compatibility.
        compatible = []
        for d in matching:
            result = _version_satisfies(installed_version, d.version_constraint)
            if result:
                compatible.append(d)
        if not compatible:
            return None, "version-mismatch"
        # Step 4: prefer most specific constraint (highest minimum version).
        # _parse_version can return None for an unparseable constraint; sort
        # those last instead of failing the comparison.
        compatible.sort(
            key=lambda d: _parse_version(d.version_constraint.lstrip(">=") or "0") or (),
            reverse=True,
        )
        matching = compatible

    # Select the best match: most specific constraint first (already sorted).
    if matching:
        decl = matching[0]
        # Final compatibility check for the selected declaration.
        if installed_version is not None:
            result = _version_satisfies(installed_version, decl.version_constraint)
            if result is False:
                return None, "version-mismatch"
        return decl, requested_version

    return None, "no-surface-id-match"


# ---------------------------------------------------------------------------
# Declaration → ResolvedSessionSurface builder (Fix 5: actual installed version)
# ---------------------------------------------------------------------------

def _build_resolved_surface(
    surface_id: str,
    provider_id: str,
    resolved_version: str,
    identity_operations: dict[SessionIdentityOperation, ControlSupport],
    ownership_modes: tuple[SessionOwnershipMode, ...],
    mapping_facts: SessionMappingFacts,
    controls: dict[SessionControlAction, ControlSupport],
    lifecycle_source: LifecycleSource,
    lifecycle_installation: LifecycleInstallation,
    correlation_id_supported: bool,
    event_ordering_guaranteed: bool,
    source_idempotency: bool,
    content_channels: tuple[ContentChannelCapability, ...],
    validation_state: SurfaceValidationState,
    effective_level: EffectiveObservationLevel,
    platforms: tuple[PlatformEvidence, ...],
) -> ResolvedSessionSurface:
    """Construct a successful ResolvedSessionSurface from declaration fields.

    ``resolved_version`` carries the *actual installed* provider version.
    Adapter refs are intentionally *not* passed into this function; they never
    appear in the foundation snapshot.
    """
    ref = SessionSurfaceRef(
        provider_id=provider_id,
        surface_id=surface_id,
        resolved_version=resolved_version,
    )
    return ResolvedSessionSurface(
        ref=ref,
        identity=SessionIdentityCapabilities(
            identity_operations=identity_operations,
            ownership_modes=ownership_modes,
            mapping_facts=mapping_facts,
        ),
        controls=controls,
        lifecycle=LifecycleObservationCapabilities(
            source=lifecycle_source,
            installation=lifecycle_installation,
            correlation_id_supported=correlation_id_supported,
            event_ordering_guaranteed=event_ordering_guaranteed,
            source_idempotency=source_idempotency,
        ),
        content=ContentStreamCapabilities(channels=content_channels),
        validation=SurfaceValidation(
            state=validation_state,
            effective_level=effective_level,
            platforms=platforms,
        ),
    )


# ---------------------------------------------------------------------------
# Inventory proof lookup (AS27 RV770 — inventory cross-check)
# ---------------------------------------------------------------------------

def _get_inventory_proof(
    provider_id: str,
    surface_id: str,
    target_platform: str,
) -> bool:
    """Check whether the AS27 inventory has local probe evidence for this
    platform on the given (provider_id, surface_id) pair.

    Returns True when:
    - The (provider_id, surface_id) is NOT in the inventory (no inventory to
      bypass — the gate does not apply to unknown surfaces).
    - The platform appears in the capability fact's ``platform_evidence``
      tuple — i.e. an exact local probe has been recorded.

    Returns False only when:
    - The surface IS in the inventory but the target platform is NOT listed
      in its ``platform_evidence`` — meaning YAML claims validation on a
      platform without local probe proof (the bypass scenario).
    """
    try:
        from audiagentic.components.providers.services.harness_observability_inventory import (
            get_harness_surface_capability_fact,
        )
    except ImportError:
        # Inventory module unavailable — conservative: no gate.
        return True

    fact = get_harness_surface_capability_fact(provider_id, surface_id)
    if fact is None:
        # Not in inventory — no bypass possible; gate does not apply.
        return True
    return target_platform in fact.platform_evidence


# ---------------------------------------------------------------------------
# Public resolver entry point (Fix 1: explicit project_root + provider_id)
# ---------------------------------------------------------------------------

def resolve_session_surface(
    project_root: Path,
    provider_id: str,
    surface_hint: SurfaceHint,
) -> ResolvedSessionSurface:
    """Resolve a surface hint into an immutable session-surface snapshot.

    Never raises — returns a supported snapshot on success or an unsupported
    snapshot with diagnostic metadata on every failure path.

    Args:
        project_root: Explicit project root for provider enablement checks.
            Must be provided by the caller; never derived from cwd.
        provider_id: Canonical provider identifier. Explicit on the API
            boundary so project-root provenance is always unambiguous.
        surface_hint: Typed request carrying surface_id and optional
            version/platform hints.

    Returns:
        A frozen :class:`ResolvedSessionSurface` instance. The
        ``resolved_version`` field contains the actual installed version
        on success, or a stable neutral value on unsupported outcomes.
    """
    # ── 1. Unknown provider ────────────────────────────────────────
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return _unsupported_snapshot(
            provider_id, surface_hint.surface_id, "unknown-provider",
            requested_version=surface_hint.version_hint,
        )

    # ── 2. Disabled provider ───────────────────────────────────────
    from audiagentic.components.providers.services.provider_config import (
        is_provider_enabled,
    )
    if not is_provider_enabled(project_root, provider_id):
        return _unsupported_snapshot(
            provider_id, surface_hint.surface_id, "disabled-provider",
            requested_version=surface_hint.version_hint,
        )

    # ── 3. Discover installed version (Fix 2) ──────────────────────
    installed_version = _probe_installed_version(descriptor)

    # ── 4. Select declaration (Fix 2: both surface_id + version match)
    declaration, requested_version = _select_declaration(
        descriptor.session_surfaces,
        surface_hint.surface_id,
        installed_version=installed_version,
        version_hint=surface_hint.version_hint,
    )
    if declaration is None:
        return _unsupported_snapshot(
            provider_id, surface_hint.surface_id, requested_version or "no-surface-id-match",
            requested_version=requested_version,
        )

    # ── 5. Blocked declaration ─────────────────────────────────────
    if declaration.validation_state == SurfaceValidationState.BLOCKED:
        return _unsupported_snapshot(
            provider_id, surface_hint.surface_id, "blocked-declaration",
            requested_version=declaration.version_constraint,
        )

    # ── 6. Platform match FIRST (Fix 4: select before enforcement) ─
    target_platform = _resolve_target_platform(surface_hint.platform_hint)
    matched_pe = _platform_matches(target_platform, declaration.platforms)
    if not matched_pe and declaration.platforms:
        return _unsupported_snapshot(
            provider_id, surface_hint.surface_id, "no-platform-match",
            requested_version=declaration.version_constraint,
        )

    # ── 7. Validation ceiling against selected PE (Fix 4) ──────────
    if matched_pe:
        eff_state = matched_pe.validation_state
        eff_level = matched_pe.effective_level
    else:
        # No per-platform evidence — fall back to declaration level.
        eff_state = declaration.validation_state
        eff_level = declaration.effective_level

    blocked, reason = _enforce_validation_ceiling(eff_level, eff_state)
    if blocked:
        return _unsupported_snapshot(
            provider_id, surface_hint.surface_id, reason,
            requested_version=declaration.version_constraint,
        )

    # ── 7b. Inventory proof gate (AS27 RV770) ─────────────────────
    # Prevent descriptor YAML from bypassing inventory evidence: a validated
    # O1+ claim on the resolved surface requires that the target platform
    # appear in the inventory's locally-validated platform_evidence for this
    # (provider_id, surface_id) pair. This gate applies only to observability
    # / effective lifecycle claim resolution; it does not prevent launching
    # a surface whose observer publication is unavailable.
    if eff_state == SurfaceValidationState.VALIDATED and eff_level.numeric >= 1:
        has_inventory_proof = _get_inventory_proof(
            provider_id, declaration.surface_id, target_platform,
        )
        if not has_inventory_proof:
            return _unsupported_snapshot(
                provider_id, surface_hint.surface_id, "no-inventory-proof",
                requested_version=declaration.version_constraint,
            )

    # ── 8. Missing adapter factory (existence check only) ──────────
    if declaration.adapter_ref:
        if not _adapter_factory_exists(declaration.adapter_ref):
            return _unsupported_snapshot(
                provider_id, surface_hint.surface_id, "missing-adapter-factory",
                requested_version=declaration.version_constraint,
            )

    # ── Success: build the resolved snapshot (Fix 5: actual version)
    actual_version = installed_version if installed_version else declaration.version_constraint
    return _build_resolved_surface(
        surface_id=declaration.surface_id,
        provider_id=provider_id,
        resolved_version=actual_version,
        identity_operations=dict(declaration.identity_operations),
        ownership_modes=declaration.ownership_modes,
        mapping_facts=declaration.mapping_facts,
        controls=dict(declaration.controls),
        lifecycle_source=declaration.lifecycle_source,
        lifecycle_installation=declaration.lifecycle_installation,
        correlation_id_supported=declaration.correlation_id_supported,
        event_ordering_guaranteed=declaration.event_ordering_guaranteed,
        source_idempotency=declaration.source_idempotency,
        content_channels=declaration.content_channels,
        validation_state=eff_state,
        effective_level=eff_level,
        platforms=declaration.platforms,
    )


# ---------------------------------------------------------------------------
# Target platform resolution (Fix 3: normalized triples)
# ---------------------------------------------------------------------------

def _resolve_target_platform(platform_hint: str | None) -> str:
    """Return the target platform as a normalised triple.

    If *platform_hint* is provided, it is used as-is (caller is responsible
    for providing the correct triple format). Otherwise the runtime detector
    produces the triple via :func:`_detect_platform_triple`.
    """
    if platform_hint:
        return platform_hint
    from audiagentic.components.providers.services.platform_target import (
        detect_platform_triple,
    )

    return detect_platform_triple()
