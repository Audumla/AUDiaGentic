"""Gateway-owned immutable execution-profile snapshots (SH07 C2).

Hosted admission uses the machine-global Agents catalog.  The in-memory
registry is an immutable admission snapshot/cache; the optional no-registry
path is retained only as an explicit unit-test seam and still reads the same
global catalog.  Project-local agent configuration is never an authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

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
    are excluded. This is the one shape global gateway admission returns;
    project-scoped execution-profile resolution is not a supported authority.

    AS105/AS101 v2: capacity (virtual_capacity/pending_capacity) is retired --
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
    immutable snapshot at admission time; scheduler state is keyed by this
    snapshot identity.

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
    binding, and generation come from here, not project-scoped config.

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
        A content digest changes exactly when the admitted profile changes,
        and is stable (idempotent) when it does not.
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

    Used for the explicit no-registry test seam.  The generation is
    deterministic from the admitted profile content.
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


class _AlwaysCurrentSnapshotValidator:
    """Validator seam for isolated tests without a live registry."""

    def resolve_snapshot(self, profile_id: str) -> ResolvedExecutionProfile:
        raise NotImplementedError(
            "snapshot resolution requires the global Agents catalog or an "
            "explicit in-memory registry"
        )

    def validate_snapshot_current(self, snapshot: ResolvedExecutionProfile) -> bool:
        return True  # No gateway authority in embedded mode; always current.


# ---------------------------------------------------------------------------
# Module-level registry selector (injectable for testing)
# ---------------------------------------------------------------------------

_gateway_registry: ExecutionProfileRegistry | None = None


def get_gateway_registry() -> ExecutionProfileRegistry | None:
    """Return the active gateway profile registry, or None for embedded mode."""
    return _gateway_registry


def set_gateway_registry(registry: ExecutionProfileRegistry | None) -> None:
    """Replace the module-level gateway profile registry.

    Pass an InMemoryExecutionProfileRegistry for shared-mode tests, or None
    for the explicit always-current test seam.
    """
    global _gateway_registry
    _gateway_registry = registry


def get_snapshot_validator() -> ExecutionProfileRegistry:
    """Return the active registry validator, or an always-current test seam.

    The registry's validate_snapshot_current is the single source of truth for
    staleness.  Admission still reads the global catalog when no registry is
    installed; this fallback only supports isolated unit tests.
    """
    reg = _gateway_registry
    if reg is not None:
        return reg
    return _AlwaysCurrentSnapshotValidator()


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

    runtime = record.get("gateway-profile-runtime") or {}
    provider_id = runtime.get("provider-id") or record.get("resolved-provider-id", "")
    params = runtime.get("params") or {}

    return ResolvedExecutionProfile(
        profile_id=profile_id,
        generation=generation,
        config_digest=config_digest,
        provider_id=provider_id,
        instances=tuple(instance_ids),
        execution_params=MappingProxyType(dict(params)),
        resolved_surface_id=runtime.get("surface-id"),
        resolved_surface_version=runtime.get("surface-version"),
    )


def profile_mapping_from_snapshot(snapshot: ResolvedExecutionProfile, record: dict[str, Any]) -> dict[str, Any]:
    runtime = record.get("gateway-profile-runtime") or {}
    return {
        "profile_id": snapshot.profile_id,
        "provider_id": snapshot.provider_id,
        "instances": list(snapshot.instances),
        "params": dict(snapshot.execution_params),
        "model_alias": runtime.get("model-alias"),
        "surface_id": snapshot.resolved_surface_id,
        "surface_version": snapshot.resolved_surface_version,
    }


def load_gateway_registry_from_agents_catalog(
    path: Path | None = None, *, required: bool = True
) -> InMemoryExecutionProfileRegistry:
    """Compile the hosted registry from the machine-global Agents catalog.

    ``agents.yaml`` is the sole declarative authority for hosted execution
    profiles.  This loader deliberately does not consult project-local
    configuration or any secondary profile document.
    """
    from audiagentic.components.agents.agents_paths import global_agents_config_path
    from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    catalog_path = path or global_agents_config_path()
    try:
        snapshot = AgentsConfigRepository(catalog_path, required=required).read(catalog_path.parent)
    except Exception as exc:  # noqa: BLE001 - configuration boundary
        raise AudiaGenticError(
            code="IO-AGW-107",
            kind="agents",
            message="required global agents catalog is unavailable",
            details={"path": str(catalog_path)},
        ) from exc

    registry = InMemoryExecutionProfileRegistry()
    for index, entry in enumerate(snapshot.document.execution_profiles):
        profile_id = entry.get("profile_id") or entry.get("profile-id")
        provider_id = entry.get("provider_id") or entry.get("provider-id")
        instances = entry.get("instances")
        params = entry.get("params", {})
        if (
            not isinstance(profile_id, str) or not profile_id.strip()
            or not isinstance(provider_id, str) or not provider_id.strip()
            or not isinstance(instances, (list, tuple)) or not instances
            or not all(isinstance(item, str) and item.strip() for item in instances)
            or not isinstance(params, Mapping)
        ):
            raise AudiaGenticError(
                code="VAL-AGW-107",
                kind="agents",
                message="global execution profile is invalid",
                details={"path": str(catalog_path), "index": index},
            )
        registry.register(
            profile_id.strip(),
            provider_id=provider_id.strip(),
            instances=tuple(item.strip() for item in instances),
            execution_params=dict(params),
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
    allow_test_fallback: bool = False,
) -> ResolvedExecutionProfile:
    """Resolve an execution profile for admission, in one schema-validated shape.

    ``surface_resolver`` is an optional ``(project_root, provider_id,
    surface_id) -> ResolvedSessionSurface`` callable, substitutable by plain-
    Python parameter injection (RV890) for tests. Defaults to
    ``providers_api.resolve_session_surface`` wrapped in the identity check.

    The machine-global Agents catalog is the sole declarative authority.  A
    hosted gateway must have its shared registry installed so admission uses
    the immutable gateway snapshot.  The optional no-registry projection is
    available only when an isolated unit test explicitly opts into it;
    project-local agent files are never consulted.

    Raises AudiaGenticError(RES-EXP-001) if the profile is not found in
    whichever source is authoritative for this process.
    Raises AudiaGenticError(RES-EXP-004) if the profile names an AS29
    surface that does not resolve or is not validated -- an explicitly
    named surface never silently falls back to the provider default.
    """
    from audiagentic.components.agents.configuration.global_catalog import (
        resolve_global_default_execution_profile,
        resolve_global_execution_profile,
    )
    registry = get_gateway_registry()
    if execution_profile_id:
        profile = resolve_global_execution_profile(project_root, execution_profile_id)
    else:
        profile = resolve_global_default_execution_profile(project_root)
    if registry is None and not allow_test_fallback:
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        raise AudiaGenticError(
            code="IO-AGW-108",
            kind="agents",
            message="shared gateway profile registry is not installed",
            details={"profile_id": profile["profile_id"]},
        )
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


def resolve_authoritative_profile(project_root: Path, profile_id: str) -> dict[str, Any]:
    """Resolve a profile from the machine-global Agents catalog."""
    from audiagentic.components.agents.configuration.global_catalog import (
        resolve_global_execution_profile,
    )

    return resolve_global_execution_profile(project_root, profile_id)


def _default_surface_resolver(project_root: Path, provider_id: str, surface_id: str) -> Any:
    """Read-only AS29 surface resolution. Launches no process."""
    from audiagentic.components.providers.providers_api import SurfaceHint, resolve_session_surface

    return resolve_session_surface(project_root, provider_id, SurfaceHint(surface_id=surface_id))
