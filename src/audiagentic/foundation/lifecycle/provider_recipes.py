"""Generic capability → provider-recipe reconciliation.

Capability components (memory today, any future capability that projects
integration into provider configs) register a reconciler here, typically from
their ``lifecycle-observer`` module. This layer stays generic: it enumerates
providers and invokes every registered reconciler. It imports no specific
capability component — the mapping "capability → provisioner" lives in the
capability, not here.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

# reconciler(project_root, enabled_provider_ids, all_provider_ids) -> result payload
ProviderRecipeReconciler = Callable[[Path, list[str], list[str]], Any]

_reconcilers: dict[str, ProviderRecipeReconciler] = {}


def register_provider_recipe_reconciler(
    capability_id: str,
    reconciler: ProviderRecipeReconciler,
) -> None:
    """Register a capability's provider-recipe reconciler (idempotent by key).

    Called by a capability component's lifecycle-observer at registration time.
    The reconciler receives the project root plus the enabled and full provider
    ID lists, and returns an opaque result payload the caller may surface.
    """
    _reconcilers[capability_id] = reconciler


def clear_provider_recipe_reconcilers() -> None:
    """Drop all registered reconcilers — test isolation helper."""
    _reconcilers.clear()


def refresh_provider_recipes(project_root: Path | str) -> dict[str, Any]:
    """Invoke every registered capability reconciler against current provider state.

    Called after a capability's config changes (e.g. memory backend configured)
    so enabled providers pick up — or drop — the integration. Best-effort and
    decoupled: capabilities with no registered reconciler simply don't run.
    """
    from audiagentic.foundation.components.loader import register_all_components

    # Ensure lifecycle-observer modules (which register reconcilers) are imported.
    register_all_components()

    root = Path(project_root)
    enabled = _enabled_provider_ids(root)
    all_ids = _all_provider_ids(root)
    out: dict[str, Any] = {}
    for capability_id, reconciler in _reconcilers.items():
        out[capability_id] = reconciler(root, enabled, all_ids)
    return out


def _enabled_provider_ids(root: Path) -> list[str]:
    """Generic query for enabled provider IDs via capability registry.

    Returns empty list if capability not registered — no fallback import (AR02).
    """
    from audiagentic.foundation.capabilities import get_capability

    resolve_enabled = get_capability("providers.provider-config.resolve_enabled")
    all_ids = _all_provider_ids(root)
    if resolve_enabled is None or not all_ids:
        return []

    return [pid for pid in all_ids if resolve_enabled(root, pid)]


def _all_provider_ids(root: Path) -> list[str]:
    """Every registered provider ID via capability registry.

    Falls back to direct import when providers observer has not yet
    self-registered (test environments with module-level state pollution).
    """
    from audiagentic.foundation.capabilities import get_capability

    all_ids_fn = get_capability("providers.descriptors.all_ids")
    if all_ids_fn is not None:
        return all_ids_fn()

    # Capability not registered — providers component absent or not yet
    # loaded. Return empty list rather than bypassing the seam with a direct
    # import (AR02). This path only fires in test harnesses where
    # register_all_components() has not imported the lifecycle-observer
    # modules that register capabilities.
    return []
