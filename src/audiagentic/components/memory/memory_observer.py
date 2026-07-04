"""Memory lifecycle observer — registers the provider-recipe reconciler.

Self-registers when imported. Import is triggered by the memory component
declaring ``lifecycle-observer`` in its YAML descriptor, which causes
``register_all_components()`` to import this module after loading descriptors.

This is the memory side of the generic reconciliation seam: the runtime layer
invokes registered reconcilers without importing memory, and memory owns the
mapping from its own config state onto the Hindsight provisioner.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.event import subscribe_component_lifecycle
from audiagentic.foundation.lifecycle.provider_recipes import (
    refresh_provider_recipes,
    register_provider_recipe_reconciler,
)

_CAPABILITY_ID = "memory"


def _reconcile(
    project_root: Path,
    enabled_provider_ids: list[str],
    all_provider_ids: list[str],
) -> dict[str, Any]:
    """Reconcile Hindsight provider integration for the current memory state.

    ``enabled`` is the on/off switch: when memory is disabled the integration is
    uninstalled from every provider, while the Hindsight config is retained so a
    later enable reinstalls it. When memory is not installed at all there is
    nothing to reconcile.
    """
    from audiagentic.foundation.components.registry import is_enabled, is_installed

    if not is_installed(_CAPABILITY_ID, project_root):
        return {"skipped": "memory not installed"}

    from audiagentic.components.memory.hindsight.provision import reconcile_hindsight

    return reconcile_hindsight(
        project_root,
        enabled_provider_ids,
        all_provider_ids=all_provider_ids,
        active=is_enabled(_CAPABILITY_ID, project_root),
    )


def _on_memory_event(project_root: Path, payload: dict, metadata: dict) -> None:
    """Re-run provider reconciliation on memory lifecycle/config changes.

    The observer is the guaranteed consumer that invokes Hindsight
    reconciliation — management tools may also reconcile synchronously for UX
    but are not required for correctness.
    """
    refresh_provider_recipes(project_root)


register_provider_recipe_reconciler(_CAPABILITY_ID, _reconcile)
subscribe_component_lifecycle(
    _CAPABILITY_ID,
    on_installed=_on_memory_event,
    on_enabled=_on_memory_event,
    on_disabled=_on_memory_event,
    on_uninstalled=_on_memory_event,
    on_config_changed=_on_memory_event,
)
