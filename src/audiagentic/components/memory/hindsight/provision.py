"""Hindsight provisioning entrypoint for the composition layer.

The memory/Hindsight implementation owns the provider-recipe matrix and all
provider-specific integration detail. Callers pass a list of provider IDs and
receive a neutral summary; they never see Hindsight internals. Whether to
install or tear down is decided here from the configured backend, not by callers.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import (
    HindsightBackendConfig,
    build_hindsight_backend,
)
from audiagentic.components.memory.hindsight.recipes import (
    apply_hindsight,
    prune_hindsight,
    teardown_hindsight,
)

# Teardown locates/removes artifacts by server name, not by backend values, but
# still needs real (non-guidance) recipes built. When no backend is configured
# this placeholder lets the removal recipes be constructed.
_TEARDOWN_BACKEND = HindsightBackendConfig(base_url="http://removed.invalid")


def reconcile_hindsight(
    project_root: Path | str,
    provider_ids: Iterable[str],
    *,
    all_provider_ids: Iterable[str] | None = None,
    active: bool = True,
) -> dict[str, Any]:
    """Apply or tear down Hindsight integration across providers.

    ``active`` is the on/off switch (memory enabled). Config is read from state
    independently, so it persists across an off→on cycle.

    active and configured   → install/verify each enabled provider's recipe;
                              prune config artifacts from the rest so a disabled
                              provider never keeps a stale entry.
    disabled or unconfigured → uninstall the integration from EVERY provider
                              (``all_provider_ids``), reversing prior installs.
                              The Hindsight config itself is left untouched.
    """
    root = Path(project_root)
    ids = list(provider_ids)
    all_ids = list(all_provider_ids) if all_provider_ids is not None else list(ids)
    backend = build_hindsight_backend(root) if active else None

    if backend is None:
        # Off (disabled) or nothing to point at (unconfigured): remove from all.
        results = teardown_hindsight(root, backend=_TEARDOWN_BACKEND, provider_ids=all_ids)
        action = "torn-down"
    else:
        results = apply_hindsight(root, backend=backend, provider_ids=ids)
        action = "applied"
        stale = [pid for pid in all_ids if pid not in set(ids)]
        if stale:
            results.update(
                prune_hindsight(root, backend=_TEARDOWN_BACKEND, provider_ids=stale)
            )

    enabled_set = set(ids)
    providers: dict[str, Any] = {}
    for pid, res in results.items():
        entry: dict[str, Any] = {
            "success": res.success,
            "state": res.state.value,
            "role": "applied" if (action == "applied" and pid in enabled_set) else (
                "uninstalled" if action == "torn-down" else "pruned-stale"
            ),
        }
        if not res.success:
            entry["error"] = res.error or res.status or "unknown failure"
        providers[pid] = entry
    return {
        "action": action,
        "providers": providers,
    }


def discover_provider_ids(project_root: Path | str) -> tuple[list[str], list[str]]:
    """Return (all_provider_ids, enabled_provider_ids).

    Provider discovery is delegated here because the memory observer must not
    import from audiagentic.components.providers directly (architecture boundary).
    The hindsight subpackage is exempt from that check and may import freely.
    Enablement is checked via the foundation features state API to avoid importing
    provider services (which would violate the architecture boundary test allowlist).
    """
    root = Path(project_root)
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.foundation.features.state import get_implementation_state

    all_ids = list(all_descriptors())
    enabled_ids = [
        pid for pid in all_ids
        if get_implementation_state(root, "providers", pid).enabled
    ]
    return all_ids, enabled_ids


def build_hindsight_status_report(project_root: Path | str) -> dict[str, Any]:
    """Build per-provider Hindsight status report for MCP/API exposure.

    Returns ``{"configured": True, "providers": {id: status}}`` when a backend
    exists, or ``{"configured": False, "providers": {}}`` otherwise. Provider
    knowledge is contained here — memory core delegates to this entry point
    without importing providers/services directly.
    """
    root = Path(project_root)
    backend = build_hindsight_backend(root)
    if backend is None:
        return {"providers": {}, "configured": False}

    from audiagentic.components.memory.hindsight.recipes import (
        build_hindsight_status,
        register_hindsight_recipes,
    )
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.components.providers.services.recipes import ProviderRecipeRegistry

    registry = ProviderRecipeRegistry()
    register_hindsight_recipes(registry, backend=backend, project_root=root)

    providers: dict[str, Any] = {}
    for provider_id in all_descriptors():
        status = build_hindsight_status(registry, provider_id, {"project_root": root})
        providers[provider_id] = status["hindsight"]

    return {"providers": providers, "configured": True}
