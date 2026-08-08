"""Gateway-owned profile snapshot and execution lane key (SH07 C2).

InMemoryExecutionProfileRegistry is the gateway-owned authority for shared gateway
mode: GatewayServiceHost loads it from the machine-scoped gateway profiles
config file (see load_gateway_registry_from_config) at startup and installs
it with set_gateway_registry(). EmbeddedCompatibilityRegistry remains the
fallback for non-shared/embedded mode, deriving a snapshot from
project-resolved profile data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redacted execution snapshot — never carries auth/env/provider secrets
# ---------------------------------------------------------------------------

_SECRET_PARAM_PREFIXES = (
    "api-key",
    "api_key",
    "api_secret",
    "secret",
    "token",
    "password",
    "auth",
)

_SECRET_PARAM_KEYS = frozenset(
    {
        "api-key",
        "api_key",
        "api_secret",
        "secret",
        "token",
        "password",
        "auth",
        "authorization",
        "bearer",
        "client-secret",
    }
)


def _strip_secrets(params: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of params with known secret keys removed."""
    stripped = {}
    for k, v in params.items():
        kl = k.lower().replace("-", "_")
        if kl in _SECRET_PARAM_KEYS or any(
            kl.startswith(prefix)
            for prefix in ("api_key", "api_secret", "secret_", "token_", "password_")
        ):
            continue
        stripped[k] = v
    return stripped


def _config_digest(params: Mapping[str, Any]) -> str:
    """Deterministic digest of non-secret execution params.

    Only stable, non-secret fields are hashed.  Two profiles with identical
    non-secret params produce the same digest regardless of provider auth
    material or other transient metadata.
    """
    redacted = _strip_secrets(params)
    # Sort keys for determinism; separators minimize whitespace noise
    encoded = json.dumps(redacted, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ResolvedExecutionProfile:
    """Immutable snapshot of an execution profile's admission configuration.

    Contains only non-secret, queue-relevant data.  The snapshot is derived at
    admission time and never modified.  Provider auth, env vars, and raw config
    are excluded. This is the one shape both project-local and shared-gateway
    resolution return -- schema-validated at construction so the two sources
    cannot silently drift (AS60 step 2).

    AS105/AS101 v2: capacity (max_concurrency/queue_max_size) is retired --
    it lives per-instance on providers' model-sources.yaml sources now, not
    on the profile. ``instances`` names the compatible source-id set;
    free-instance dispatch binds to one of them only at dispatch time.
    """

    profile_id: str
    generation: str
    config_digest: str
    provider_id: str
    instances: tuple[str, ...]
    execution_params: Mapping[str, Any]
    # AS82: resolved AS29 surface identity, when the profile named one.
    # Requested (ExecutionProfile.surface_id) vs resolved are kept distinct
    # elsewhere -- these are the resolved identity, carried once so
    # downstream consumers read it rather than re-resolving.
    resolved_surface_id: str | None = None
    resolved_surface_version: str | None = None

    def __post_init__(self) -> None:
        from audiagentic.foundation.contracts.errors import AudiaGenticError
        from audiagentic.foundation.contracts.schema_registry import validate_with_schema

        errors = validate_with_schema("resolved-execution-profile", self.to_mapping())
        if errors:
            raise AudiaGenticError(
                code="VAL-EXP-005",
                kind="agents",
                message="resolved execution profile failed schema validation",
                details={"profile_id": self.profile_id, "issues": errors},
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "profile-id": self.profile_id,
            "generation": self.generation,
            "config-digest": self.config_digest,
            "provider-id": self.provider_id,
            "instances": list(self.instances),
            "execution-params": dict(self.execution_params),
            "resolved-surface-id": self.resolved_surface_id,
            "resolved-surface-version": self.resolved_surface_version,
        }


# ---------------------------------------------------------------------------
# Gateway profile registry (SH07 C2)
# ---------------------------------------------------------------------------


class ExecutionProfileRegistry(Protocol):
    """Gateway-owned authority for execution profile snapshots.

    In shared gateway mode, this registry resolves the authoritative snapshot
    for a profile id.  Project-local config is not authoritative for queue
    limits, provider/model binding, or generation.  The registry provides an
    immutable snapshot at admission time; queue lanes are keyed by that
    snapshot's lane key.

    When a full admin API ships, this protocol will be implemented by a
    service-side component backed by persistent configuration (TODO: replace
    InMemoryExecutionProfileRegistry with the real implementation).
    """

    def resolve_snapshot(self, profile_id: str) -> ResolvedExecutionProfile:
        """Resolve the current gateway snapshot for a profile id.

        Raises RES-EXP-001 equivalent if the profile is not found.
        """
        ...

    def validate_snapshot_current(self, snapshot: ResolvedExecutionProfile) -> bool:
        """Return True if the snapshot's generation/digest still matches current.

        A stale result means the gateway profile changed after this snapshot
        was resolved; pending queued work must be terminal-rejected.
        """
        ...


# ---------------------------------------------------------------------------
# In-memory test/shared-mode registry (transitional until admin API ships)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExecutionProfileDef:
    """Immutable gateway-owned profile definition stored in the registry."""

    provider_id: str
    instances: tuple[str, ...]
    generation: str
    execution_params: Mapping[str, Any] = None  # type: ignore[assignment]


class InMemoryExecutionProfileRegistry:
    """In-memory gateway profile registry — transitional until admin API ships.

    Stores gateway-owned profile definitions keyed by profile id.  This is the
    authoritative source for shared gateway mode: queue limits, provider/model
    binding, and generation come from here, not project-local config.

    Each call to register() increments an internal version counter so the
    generated generation changes on every update — making stale-generation
    testing straightforward without manual generation management.

    TODO: replace with a persistent service-side registry backed by the admin
    API (YAML/DB).  For now, this allows tests to exercise shared-mode behavior
    and demonstrates the architecture seam.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, _ExecutionProfileDef] = {}

    def register(
        self,
        profile_id: str,
        *,
        provider_id: str,
        instances: tuple[str, ...],
        generation: str | None = None,
        execution_params: Mapping[str, Any] | None = None,
    ) -> None:
        """Register or update a gateway-owned profile definition.

        ``generation`` is content-derived (a digest of provider/instances
        and non-secret execution params) rather than an incrementing counter:
        callers such as ``load_gateway_registry_from_config`` build a fresh
        registry instance on every reload, so a per-instance counter would
        reset to the same value every time and generation would never
        actually change across a config edit — silently breaking the
        stale-generation rejection (CON-AGW-101) this registry exists to
        support. A content digest changes exactly when the config changes,
        and is stable (idempotent) when it doesn't.
        """
        params = execution_params or {}
        if generation is None:
            gen_payload = json.dumps(
                {
                    "profile_id": profile_id,
                    "provider_id": provider_id,
                    "instances": list(instances),
                    "params_digest": _config_digest(params),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            generation = "gen_" + hashlib.sha256(gen_payload.encode("utf-8")).hexdigest()[:12]

        self._profiles[profile_id] = _ExecutionProfileDef(
            provider_id=provider_id,
            instances=tuple(instances),
            generation=generation,
            execution_params=params,
        )

    def resolve_snapshot(self, profile_id: str) -> ResolvedExecutionProfile:
        """Resolve the current gateway snapshot for a profile id."""
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        defn = self._profiles.get(profile_id)
        if defn is None:
            raise AudiaGenticError(
                code="RES-EXP-001",
                kind="agents",
                message=f"gateway profile not found: {profile_id!r}",
                details={"profile-id": profile_id},
            )
        redacted_params = _strip_secrets(defn.execution_params)
        config_digest = _config_digest(redacted_params)

        return ResolvedExecutionProfile(
            profile_id=profile_id,
            generation=defn.generation,
            config_digest=config_digest,
            provider_id=defn.provider_id,
            instances=defn.instances,
            execution_params=MappingProxyType(dict(redacted_params)),
        )

    def validate_snapshot_current(self, snapshot: ResolvedExecutionProfile) -> bool:
        """Check if the snapshot's generation matches the current registry entry."""
        defn = self._profiles.get(snapshot.profile_id)
        if defn is None:
            return False  # Profile removed — stale
        return (
            defn.generation == snapshot.generation
            and _config_digest(_strip_secrets(defn.execution_params)) == snapshot.config_digest
        )


# ---------------------------------------------------------------------------
# Embedded compatibility registry (non-shared mode)
# ---------------------------------------------------------------------------


def snapshot_from_resolved_profile(
    profile_id: str,
    provider_id: str,
    instances: tuple[str, ...],
    params: Mapping[str, Any],
) -> ResolvedExecutionProfile:
    """Build a ResolvedExecutionProfile from already-resolved project profile data.

    Used by EmbeddedCompatibilityRegistry when no shared gateway registry is
    active.  The generation is deterministic from (profile_id + config_digest)
    so two projects with identical non-secret configs produce the same generation.
    """
    config_digest = _config_digest(params)
    gen_payload = json.dumps(
        {"profile_id": profile_id, "config_digest": config_digest},
        sort_keys=True,
        separators=(",", ":"),
    )
    generation = "gen_" + hashlib.sha256(gen_payload.encode("utf-8")).hexdigest()[:12]

    redacted_params = _strip_secrets(params)

    return ResolvedExecutionProfile(
        profile_id=profile_id,
        generation=generation,
        config_digest=config_digest,
        provider_id=provider_id,
        instances=tuple(instances),
        execution_params=MappingProxyType(dict(redacted_params)),
    )


class EmbeddedCompatibilityRegistry:
    """Derives snapshots from project-resolved profile data (non-shared mode).

    In embedded/non-shared mode, there is no gateway-wide registry — the
    snapshot comes from whatever the project-local resolver returned.  This
    is a transitional fallback; shared gateway mode uses InMemoryExecutionProfileRegistry.
    """

    def resolve_snapshot(self, profile_id: str) -> ResolvedExecutionProfile:
        raise NotImplementedError(
            "EmbeddedCompatibilityRegistry.resolve_snapshot requires project "
            "profile resolution context — use snapshot_from_resolved_profile() directly "
            "or switch to shared-mode registry."
        )

    def validate_snapshot_current(self, snapshot: ResolvedExecutionProfile) -> bool:
        return True  # No gateway authority in embedded mode; always current.


# ---------------------------------------------------------------------------
# Module-level registry selector (injectable for testing)
# ---------------------------------------------------------------------------

_gateway_registry: ExecutionProfileRegistry | None = None
_gateway_registry_lock = threading.Lock()
_gateway_registry_config_path: Path | None = None


def get_gateway_registry() -> ExecutionProfileRegistry | None:
    """Return the active gateway profile registry, or None for embedded mode."""
    return _gateway_registry


def set_gateway_registry(registry: ExecutionProfileRegistry | None) -> None:
    """Replace the module-level gateway profile registry.

    Pass an InMemoryExecutionProfileRegistry for shared-mode tests, or None to fall back
    to embedded compatibility (project-resolved profiles).
    """
    global _gateway_registry
    _gateway_registry = registry


def set_gateway_registry_config_path(path: Path | None) -> None:
    """Record the config path used for the current registry.

    Used by reload_profile_registry to re-read from the same source.
    """
    global _gateway_registry_config_path
    _gateway_registry_config_path = path


def get_gateway_registry_config_path() -> Path | None:
    """Return the config path used for the current registry, or None."""
    return _gateway_registry_config_path


def _profile_generation_summary(registry: InMemoryExecutionProfileRegistry) -> dict[str, Any]:
    """Return a redacted summary of profile generations (no secrets).

    Used for reload status output — carries only profile ids, generation
    strings, and config digests. Provider auth material is excluded.
    """
    profiles: list[dict[str, Any]] = []
    for profile_id, defn in registry._profiles.items():  # noqa: SLF001
        params_digest = _config_digest(_strip_secrets(defn.execution_params))
        profiles.append(
            {
                "profile-id": profile_id,
                "generation": defn.generation,
                "config-digest": params_digest,
                "provider-id": defn.provider_id,
                "instances": list(defn.instances),
            }
        )
    return {"profiles": profiles}


def _build_registry_on_worker_thread(config_path: Path) -> InMemoryExecutionProfileRegistry | None:
    """Load and validate a candidate registry on a worker thread.

    SH13 step 3: building the new registry off-thread prevents blocking the
    calling thread during config I/O and YAML parsing — important when reload
    is called from an MCP tool call or HTTP handler that has transport-level
    deadlines.

    Returns None when *config_path* does not exist (embedded fallback).
    Raises AudiaGenticError(IO-AGW-107) on a malformed file.
    """
    return load_gateway_registry_from_config(config_path)


def reload_profile_registry(
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically reload the gateway profile registry from config.

    Build a new InMemoryExecutionProfileRegistry from *config_path* (or the originally
    recorded config path), validate it off-thread, and swap the module-level
    pointer under a short lock.  On failure the previous registry is retained.

    On successful reload a redacted ``agents.execution.gateway.profile-reloaded``
    event is published on the event bus with only profile ids, generation
    strings, and config digests — no provider auth material (SH13 step 4).

    Returns a redacted summary of the reload outcome:
    - ``success``: bool — whether the swap succeeded
    - ``old-generation-summary``: redacted profile list before the swap (if any)
    - ``new-generation-summary``: redacted profile list after the swap (on success)
    - ``error``: dict with code/message/details on failure

    Raises AudiaGenticError if no registry is currently installed (embedded
    mode has nothing to reload).
    """
    global _gateway_registry  # noqa: PLW0603
    from concurrent.futures import ThreadPoolExecutor

    from audiagentic.foundation.contracts.errors import AudiaGenticError

    current = _gateway_registry
    if current is None:
        raise AudiaGenticError(
            code="CON-AGW-102",
            kind="agents",
            message="no shared gateway registry installed; reload requires shared mode",
            details={"registry-present": False},
        )

    # Resolve source path
    resolved_path = config_path or _gateway_registry_config_path
    if resolved_path is None:
        raise AudiaGenticError(
            code="VAL-AGW-092",
            kind="agents",
            message="no config path available for registry reload",
            details={
                "config-path-provided": bool(config_path),
                "recorded-path": bool(_gateway_registry_config_path),
            },
        )

    # Capture old summary before attempting swap
    old_summary = (
        _profile_generation_summary(current) if isinstance(current, InMemoryExecutionProfileRegistry) else {}
    )

    # SH13 step 3: build new registry off-thread so config I/O + YAML parsing
    # does not block the calling thread (MCP tool call / HTTP handler).
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="gateway-reload") as executor:
        future = executor.submit(_build_registry_on_worker_thread, resolved_path)
        try:
            new_registry = future.result(timeout=30)
        except Exception as exc:
            # Re-wrap so the caller gets a consistent error shape
            if isinstance(exc, AudiaGenticError):
                return {
                    "success": False,
                    "old-generation-summary": old_summary,
                    "error": {"code": exc.code, "message": str(exc), "kind": "agents"},
                }
            return {
                "success": False,
                "old-generation-summary": old_summary,
                "error": {
                    "code": "IO-AGW-108",
                    "message": f"failed to build candidate registry: {exc}",
                    "kind": "agents",
                },
            }

    # new_registry is None when config file vanished; treat as failure
    if new_registry is None:
        return {
            "success": False,
            "old-generation-summary": old_summary,
            "error": {
                "code": "IO-AGW-109",
                "message": "gateway profiles config file missing; reload aborted",
                "kind": "agents",
                "details": {"path": str(resolved_path)},
            },
        }

    # Atomic swap under lock
    with _gateway_registry_lock:
        old_registry = _gateway_registry
        if old_registry is None:
            # Registry was cleared concurrently; retain the attempt
            return {
                "success": False,
                "old-generation-summary": {},
                "error": {
                    "code": "CON-AGW-102",
                    "message": "registry was cleared during reload; retry",
                    "kind": "agents",
                },
            }
        _gateway_registry = new_registry

    # Build redacted new summary (no secrets)
    new_summary = _profile_generation_summary(new_registry)

    logger.info(
        "gateway profile registry reloaded",
        extra={
            "config-path": str(resolved_path),
            "old-profile-count": len(old_summary.get("profiles", [])),
            "new-profile-count": len(new_summary.get("profiles", [])),
        },
    )

    # SH13 step 4: publish redacted profile-generation-changed event on success.
    # Only carries profile ids, generation strings, config digests — never
    # provider auth material or filesystem paths beyond the config file name.
    try:
        from audiagentic.components.agents.gateway.event_topics import (
            GATEWAY_PROFILE_RELOADED_TOPIC,
        )
        from audiagentic.foundation.event import get_bus

        get_bus().publish(
            GATEWAY_PROFILE_RELOADED_TOPIC,
            {
                "config-path": resolved_path.name,
                "old-generation-summary": old_summary,
                "new-generation-summary": new_summary,
            },
            metadata={},
        )
    except Exception:  # noqa: BLE001 — event publish must not break reload
        logger.warning(
            "failed to publish profile-reloaded event",
            exc_info=True,
        )

    return {
        "success": True,
        "old-generation-summary": old_summary,
        "new-generation-summary": new_summary,
    }


def get_snapshot_validator() -> ExecutionProfileRegistry:
    """Return a validator tied to the active registry, or embedded fallback.

    The registry's validate_snapshot_current is the single source of truth for
    staleness.  When no registry is set (embedded mode), returns an always-current
    validator that preserves existing behavior.
    """
    reg = _gateway_registry
    if reg is not None:
        return reg
    return EmbeddedCompatibilityRegistry()


def snapshot_from_record(record: dict[str, Any]) -> ResolvedExecutionProfile | None:
    """Reconstruct a ResolvedExecutionProfile from persisted record fields.

    Used by the queue manager (enqueue) to recover the admission-time snapshot
    without re-deriving it from mutable caller params.  Returns None if the
    record lacks snapshot identity fields (pre-SH07 C2 records).

    AS105/AS101 decided fail-mode: a record admitted under a shared-gateway
    snapshot (gateway-profile-id present) but written before the
    free-instance dispatch pivot has no ``resolved-instance-ids`` to
    reconstruct from -- raise rather than silently misparse it as an
    empty/degenerate instance set.
    """
    profile_id = record.get("gateway-profile-id")
    generation = record.get("gateway-profile-generation")
    config_digest = record.get("gateway-profile-config-digest")
    if not profile_id or not generation or not config_digest:
        return None

    instance_ids = record.get("resolved-instance-ids")
    if instance_ids is None:
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        raise AudiaGenticError(
            code="VAL-EXP-006",
            kind="agents",
            message="gateway request record predates the free-instance dispatch "
            "migration (AS105/AS101); resubmit required",
            details={"request-id": record.get("request-id")},
        )

    provider_id = record.get("resolved-provider-id", "")

    return ResolvedExecutionProfile(
        profile_id=profile_id,
        generation=generation,
        config_digest=config_digest,
        provider_id=provider_id,
        instances=tuple(instance_ids),
        execution_params=MappingProxyType({}),  # not needed for queue ops
    )


# ---------------------------------------------------------------------------
# Gateway-owned config loading (SH07 C2/RV745 — service-host startup wiring)
# ---------------------------------------------------------------------------


def load_gateway_registry_from_config(path: Path) -> InMemoryExecutionProfileRegistry | None:
    """Build an InMemoryExecutionProfileRegistry from a gateway profiles config file.

    Returns None (embedded fallback) when *path* does not exist, so a fresh
    machine with no shared-gateway config keeps prior embedded-mode behavior.
    The file uses the same profile-list shape as execution-profiles.yaml but is
    gateway-scoped (machine home config, not project-local). AS105/AS101:
    each entry's ``instances`` names the compatible model-sources.yaml
    source-id set; capacity comes from those sources, not from gateway-owned
    queue limits.  Raises AudiaGenticError(IO-AGW-107) on a malformed file.
    """
    if not path.exists():
        return None

    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.io import load_yaml_file

    try:
        data = load_yaml_file(path)
    except Exception as exc:
        raise AudiaGenticError(
            code="IO-AGW-107",
            kind="agents",
            message="failed to read gateway profiles config",
            details={"path": str(path)},
        ) from exc

    registry = InMemoryExecutionProfileRegistry()
    for entry in (data or {}).get("profiles", []):
        profile_id = entry.get("profile_id") or entry.get("profile-id")
        provider_id = entry.get("provider_id") or entry.get("provider-id")
        instances = entry.get("instances")
        if not profile_id or not provider_id or not instances:
            logger.warning(
                "skipping gateway profile config entry missing profile_id/provider_id/instances",
                extra={"path": str(path)},
            )
            continue
        params = entry.get("params") or {}
        registry.register(
            profile_id,
            provider_id=provider_id,
            instances=tuple(instances),
            execution_params=params,
        )
    return registry


# ---------------------------------------------------------------------------
# The one public resolver contract (AS60 step 2)
# ---------------------------------------------------------------------------


def resolve_for_admission(
    project_root: Path,
    execution_profile_id: str | None,
    *,
    surface_resolver: Any = None,
) -> ResolvedExecutionProfile:
    """Resolve an execution profile for admission, in one schema-validated shape.

    ``surface_resolver`` is an optional ``(project_root, provider_id,
    surface_id) -> ResolvedSessionSurface`` callable, substitutable by plain-
    Python parameter injection (RV890) for tests. Defaults to
    ``providers_api.resolve_session_surface`` wrapped in the identity check.

    Project-local resolution stays a plain function call -- it is stateless,
    so there is nothing composition needs to own. When a shared-gateway
    registry is installed for this process, it is authoritative for
    provider/instances instead; project-local data only selects
    which gateway profile id to reference (SH07 C2). Callers no longer need
    to know which source answered -- both return the same
    ResolvedExecutionProfile.

    Raises AudiaGenticError(RES-EXP-001) if the profile is not found in
    whichever source is authoritative for this process.
    Raises AudiaGenticError(RES-EXP-004) if the profile names an AS29
    surface that does not resolve or is not validated -- an explicitly
    named surface never silently falls back to the provider default.
    """
    from audiagentic.components.agents.models.execution_profile_api import (
        resolve_default_execution_profile,
        resolve_execution_profile,
    )

    if execution_profile_id:
        profile = resolve_execution_profile(project_root, execution_profile_id)
    else:
        profile = resolve_default_execution_profile(project_root)

    registry = get_gateway_registry()
    if registry is not None:
        snapshot = registry.resolve_snapshot(profile["profile_id"])
    else:
        snapshot = snapshot_from_resolved_profile(
            profile["profile_id"],
            profile["provider_id"],
            tuple(profile["instances"]),
            profile.get("params", {}),
        )

    surface_id = profile.get("surface_id")
    if not surface_id:
        return snapshot

    if surface_resolver is None:
        surface_resolver = _default_surface_resolver

    resolved_surface = surface_resolver(project_root, snapshot.provider_id, surface_id)
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    if not resolved_surface.validation.evidence.validated:
        raise AudiaGenticError(
            code="RES-EXP-004",
            kind="agents",
            message="execution profile names a session surface that is not resolvable or not validated",
            details={"provider_id": snapshot.provider_id, "surface_id": surface_id},
        )
    return replace(
        snapshot,
        resolved_surface_id=resolved_surface.ref.surface_id,
        resolved_surface_version=resolved_surface.ref.resolved_version,
    )


def _default_surface_resolver(project_root: Path, provider_id: str, surface_id: str) -> Any:
    """Read-only AS29 surface resolution. Launches no process."""
    from audiagentic.components.providers.contracts.session_surface import SurfaceHint
    from audiagentic.components.providers.providers_api import resolve_session_surface

    return resolve_session_surface(project_root, provider_id, SurfaceHint(surface_id=surface_id))
