"""Gateway-owned profile snapshot and execution lane key (SH07 C2).

InMemoryGatewayRegistry is the gateway-owned authority for shared gateway
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
from dataclasses import dataclass
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

_SECRET_PARAM_KEYS = frozenset({
    "api-key", "api_key", "api_secret", "secret", "token", "password",
    "auth", "authorization", "bearer", "client-secret",
})


def _strip_secrets(params: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of params with known secret keys removed."""
    stripped = {}
    for k, v in params.items():
        kl = k.lower().replace("-", "_")
        if kl in _SECRET_PARAM_KEYS or any(
            kl.startswith(prefix) for prefix in ("api_key", "api_secret", "secret_", "token_", "password_")
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


def _admission_policy_digest(
    max_concurrency: int,
    queue_max_size: int,
) -> str:
    """Deterministic digest of the admission policy (queue limits).

    Two profiles with the same limits produce the same admission policy
    digest, even if their execution params differ.
    """
    payload = json.dumps(
        {"max_concurrency": max_concurrency, "queue_max_size": queue_max_size},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class GatewayProfileSnapshot:
    """Immutable snapshot of a gateway profile's execution configuration.

    Contains only non-secret, queue-relevant data.  The snapshot is derived at
    admission time and never modified.  Provider auth, env vars, and raw config
    are excluded.
    """

    profile_id: str
    generation: str
    config_digest: str
    provider_id: str
    model_id: str | None
    max_concurrency: int
    queue_max_size: int
    execution_params: Mapping[str, Any]
    admission_policy_digest: str

    def lane_key(self) -> GatewayExecutionLaneKey:
        return GatewayExecutionLaneKey(
            profile_id=self.profile_id,
            generation=self.generation,
            config_digest=self.config_digest,
        )


# ---------------------------------------------------------------------------
# Lane key — stable identity for a queue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GatewayExecutionLaneKey:
    """Stable, hashable identity for a gateway execution lane.

    Two profiles that resolve to the same (profile_id, generation, config_digest)
    share one physical queue lane — even if they come from different projects.
    """

    profile_id: str
    generation: str
    config_digest: str

    def public_id(self) -> str:
        """Human-readable lane identifier with no project paths or secrets."""
        short_digest = self.config_digest.replace("sha256:", "")[:12]
        return f"{self.profile_id}/{self.generation}/{short_digest}"


# ---------------------------------------------------------------------------
# Gateway profile registry (SH07 C2)
# ---------------------------------------------------------------------------

class GatewayProfileRegistry(Protocol):
    """Gateway-owned authority for execution profile snapshots.

    In shared gateway mode, this registry resolves the authoritative snapshot
    for a profile id.  Project-local config is not authoritative for queue
    limits, provider/model binding, or generation.  The registry provides an
    immutable snapshot at admission time; queue lanes are keyed by that
    snapshot's lane key.

    When a full admin API ships, this protocol will be implemented by a
    service-side component backed by persistent configuration (TODO: replace
    InMemoryGatewayRegistry with the real implementation).
    """

    def resolve_snapshot(self, profile_id: str) -> GatewayProfileSnapshot:
        """Resolve the current gateway snapshot for a profile id.

        Raises RES-AGP-001 equivalent if the profile is not found.
        """
        ...

    def validate_snapshot_current(self, snapshot: GatewayProfileSnapshot) -> bool:
        """Return True if the snapshot's generation/digest still matches current.

        A stale result means the gateway profile changed after this snapshot
        was resolved; pending queued work must be terminal-rejected.
        """
        ...


# ---------------------------------------------------------------------------
# In-memory test/shared-mode registry (transitional until admin API ships)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _GatewayProfileDef:
    """Immutable gateway-owned profile definition stored in the registry."""
    provider_id: str
    model_id: str | None
    generation: str
    max_concurrency: int = 1
    queue_max_size: int = 8
    execution_params: Mapping[str, Any] = None  # type: ignore[assignment]


class InMemoryGatewayRegistry:
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
        self._profiles: dict[str, _GatewayProfileDef] = {}
        self._versions: dict[str, int] = {}

    def register(
        self,
        profile_id: str,
        *,
        provider_id: str,
        model_id: str | None = None,
        generation: str | None = None,
        max_concurrency: int = 1,
        queue_max_size: int = 8,
        execution_params: Mapping[str, Any] | None = None,
    ) -> None:
        """Register or update a gateway-owned profile definition."""
        self._versions[profile_id] = self._versions.get(profile_id, 0) + 1
        if generation is None:
            gen_payload = json.dumps(
                {"profile_id": profile_id, "provider_id": provider_id, "version": self._versions[profile_id]},
                sort_keys=True, separators=(",", ":"),
            )
            generation = "gen_" + hashlib.sha256(gen_payload.encode("utf-8")).hexdigest()[:12]

        params = execution_params or {}

        self._profiles[profile_id] = _GatewayProfileDef(
            provider_id=provider_id,
            model_id=model_id,
            generation=generation,
            max_concurrency=max_concurrency,
            queue_max_size=queue_max_size,
            execution_params=params,
        )

    def resolve_snapshot(self, profile_id: str) -> GatewayProfileSnapshot:
        """Resolve the current gateway snapshot for a profile id."""
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        defn = self._profiles.get(profile_id)
        if defn is None:
            raise AudiaGenticError(
                code="RES-AGP-001",
                kind="agents",
                message=f"gateway profile not found: {profile_id!r}",
                details={"profile-id": profile_id},
            )
        redacted_params = _strip_secrets(defn.execution_params)
        config_digest = _config_digest(redacted_params)
        admission_policy_digest = _admission_policy_digest(
            defn.max_concurrency, defn.queue_max_size,
        )

        return GatewayProfileSnapshot(
            profile_id=profile_id,
            generation=defn.generation,
            config_digest=config_digest,
            provider_id=defn.provider_id,
            model_id=defn.model_id,
            max_concurrency=defn.max_concurrency,
            queue_max_size=defn.queue_max_size,
            execution_params=MappingProxyType(dict(redacted_params)),
            admission_policy_digest=admission_policy_digest,
        )

    def validate_snapshot_current(self, snapshot: GatewayProfileSnapshot) -> bool:
        """Check if the snapshot's generation matches the current registry entry."""
        defn = self._profiles.get(snapshot.profile_id)
        if defn is None:
            return False  # Profile removed — stale
        return defn.generation == snapshot.generation and _config_digest(
            _strip_secrets(defn.execution_params)
        ) == snapshot.config_digest


# ---------------------------------------------------------------------------
# Embedded compatibility registry (non-shared mode)
# ---------------------------------------------------------------------------

def snapshot_from_resolved_profile(
    profile_id: str,
    provider_id: str,
    model_id: str | None,
    params: Mapping[str, Any],
) -> GatewayProfileSnapshot:
    """Build a GatewayProfileSnapshot from already-resolved project profile data.

    Used by EmbeddedCompatibilityRegistry when no shared gateway registry is
    active.  The generation is deterministic from (profile_id + config_digest)
    so two projects with identical non-secret configs produce the same generation.
    """
    config_digest = _config_digest(params)
    gen_payload = json.dumps(
        {"profile_id": profile_id, "config_digest": config_digest},
        sort_keys=True, separators=(",", ":"),
    )
    generation = "gen_" + hashlib.sha256(gen_payload.encode("utf-8")).hexdigest()[:12]

    max_concurrency = 1
    queue_max_size = 8
    for key in ("max-concurrency", "max_concurrency"):
        if key in params and isinstance(params[key], int) and not isinstance(params[key], bool):
            max_concurrency = max(1, params[key])
            break
    for key in ("queue-max-size", "queue_max_size"):
        if key in params and isinstance(params[key], int) and not isinstance(params[key], bool):
            queue_max_size = max(1, params[key])
            break
    if not any(k in params for k in ("queue-max-size", "queue_max_size")):
        queue_max_size = max(8, max_concurrency * 2)

    redacted_params = _strip_secrets(params)
    admission_policy_digest = _admission_policy_digest(max_concurrency, queue_max_size)

    return GatewayProfileSnapshot(
        profile_id=profile_id,
        generation=generation,
        config_digest=config_digest,
        provider_id=provider_id,
        model_id=model_id,
        max_concurrency=max_concurrency,
        queue_max_size=queue_max_size,
        execution_params=MappingProxyType(dict(redacted_params)),
        admission_policy_digest=admission_policy_digest,
    )


class EmbeddedCompatibilityRegistry:
    """Derives snapshots from project-resolved profile data (non-shared mode).

    In embedded/non-shared mode, there is no gateway-wide registry — the
    snapshot comes from whatever the project-local resolver returned.  This
    is a transitional fallback; shared gateway mode uses InMemoryGatewayRegistry.
    """

    def resolve_snapshot(self, profile_id: str) -> GatewayProfileSnapshot:
        raise NotImplementedError(
            "EmbeddedCompatibilityRegistry.resolve_snapshot requires project "
            "profile resolution context — use snapshot_from_resolved_profile() directly "
            "or switch to shared-mode registry."
        )

    def validate_snapshot_current(self, snapshot: GatewayProfileSnapshot) -> bool:
        return True  # No gateway authority in embedded mode; always current.


# ---------------------------------------------------------------------------
# Module-level registry selector (injectable for testing)
# ---------------------------------------------------------------------------

_gateway_registry: GatewayProfileRegistry | None = None
_gateway_registry_lock = threading.Lock()
_gateway_registry_config_path: Path | None = None


def get_gateway_registry() -> GatewayProfileRegistry | None:
    """Return the active gateway profile registry, or None for embedded mode."""
    return _gateway_registry


def set_gateway_registry(registry: GatewayProfileRegistry | None) -> None:
    """Replace the module-level gateway profile registry.

    Pass an InMemoryGatewayRegistry for shared-mode tests, or None to fall back
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


def _profile_generation_summary(registry: InMemoryGatewayRegistry) -> dict[str, Any]:
    """Return a redacted summary of profile generations (no secrets).

    Used for reload status output — carries only profile ids, generation
    strings, and config digests. Provider auth material is excluded.
    """
    profiles: list[dict[str, str]] = []
    for profile_id, defn in registry._profiles.items():  # noqa: SLF001
        params_digest = _config_digest(_strip_secrets(defn.execution_params))
        profiles.append({
            "profile-id": profile_id,
            "generation": defn.generation,
            "config-digest": params_digest,
            "provider-id": defn.provider_id,
            "model-id": defn.model_id,
            "max-concurrency": defn.max_concurrency,
            "queue-max-size": defn.queue_max_size,
        })
    return {"profiles": profiles}


def _build_registry_on_worker_thread(config_path: Path) -> InMemoryGatewayRegistry | None:
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

    Build a new InMemoryGatewayRegistry from *config_path* (or the originally
    recorded config path), validate it off-thread, and swap the module-level
    pointer under a short lock.  On failure the previous registry is retained.

    On successful reload a redacted ``agents.llm.gateway.profile-reloaded``
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
            details={"config-path-provided": bool(config_path), "recorded-path": bool(_gateway_registry_config_path)},
        )

    # Capture old summary before attempting swap
    old_summary = _profile_generation_summary(current) if isinstance(current, InMemoryGatewayRegistry) else {}

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
        from audiagentic.components.agents.agents_event_topics import (
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


def get_snapshot_validator() -> GatewayProfileRegistry:
    """Return a validator tied to the active registry, or embedded fallback.

    The registry's validate_snapshot_current is the single source of truth for
    staleness.  When no registry is set (embedded mode), returns an always-current
    validator that preserves existing behavior.
    """
    reg = _gateway_registry
    if reg is not None:
        return reg
    return EmbeddedCompatibilityRegistry()


def snapshot_from_record(record: dict[str, Any]) -> GatewayProfileSnapshot | None:
    """Reconstruct a GatewayProfileSnapshot from persisted record fields.

    Used by the queue manager (enqueue) to recover the admission-time snapshot
    without re-deriving it from mutable caller params.  Returns None if the
    record lacks snapshot identity fields (pre-SH07 C2 records).
    """
    profile_id = record.get("gateway-profile-id")
    generation = record.get("gateway-profile-generation")
    config_digest = record.get("gateway-profile-config-digest")
    if not profile_id or not generation or not config_digest:
        return None

    provider_id = record.get("resolved-provider-id", "")
    model_id = record.get("resolved-model-id")
    queue_limits = record.get("resolved-queue-limits") or {}
    max_concurrency = queue_limits.get("max-concurrency", 1)
    queue_max_size = queue_limits.get("queue-max-size", 8)
    admission_policy_digest = record.get("admission-policy-digest", "")

    return GatewayProfileSnapshot(
        profile_id=profile_id,
        generation=generation,
        config_digest=config_digest,
        provider_id=provider_id,
        model_id=model_id,
        max_concurrency=max_concurrency,
        queue_max_size=queue_max_size,
        execution_params=MappingProxyType({}),  # not needed for queue ops
        admission_policy_digest=admission_policy_digest or "",
    )


# ---------------------------------------------------------------------------
# Gateway-owned config loading (SH07 C2/RV745 — service-host startup wiring)
# ---------------------------------------------------------------------------

def load_gateway_registry_from_config(path: Path) -> InMemoryGatewayRegistry | None:
    """Build an InMemoryGatewayRegistry from a gateway profiles config file.

    Returns None (embedded fallback) when *path* does not exist, so a fresh
    machine with no shared-gateway config keeps prior embedded-mode behavior.
    The file uses the same profile-list shape as agent-profiles.yaml but is
    gateway-scoped (machine home config, not project-local), reinterpreting
    each entry's ``max-concurrency``/``queue-max-size`` params as gateway-owned
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

    registry = InMemoryGatewayRegistry()
    for entry in (data or {}).get("profiles", []):
        profile_id = entry.get("profile_id") or entry.get("profile-id")
        provider_id = entry.get("provider_id") or entry.get("provider-id")
        if not profile_id or not provider_id:
            logger.warning(
                "skipping gateway profile config entry missing profile_id/provider_id",
                extra={"path": str(path)},
            )
            continue
        params = entry.get("params") or {}
        max_concurrency = params.get("max-concurrency", params.get("max_concurrency", 1))
        queue_max_size = params.get("queue-max-size", params.get("queue_max_size", 8))
        registry.register(
            profile_id,
            provider_id=provider_id,
            model_id=entry.get("model_id") or entry.get("model-id"),
            max_concurrency=max_concurrency,
            queue_max_size=queue_max_size,
            execution_params=params,
        )
    return registry
