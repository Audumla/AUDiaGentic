"""Provider surface lifecycle observer.

Subscribes to lifecycle.component.* events on the foundation event bus.
On component install: applies surface contributions for all installed providers.
On component uninstall: prunes stale blocks then re-applies remaining contributions.

This module self-registers when imported. Import is triggered by the providers component
declaring lifecycle-observer in its YAML descriptor, which causes register_all_components()
to import this module after loading descriptors.

Neither this module nor the lifecycle layer know about each other directly —
decoupled via the event bus.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.event import get_bus

from .manager import apply_provider_surfaces, prune_provider_surfaces


def _on_component_lifecycle(event_type: str, payload: dict, metadata: dict) -> None:
    project_root = payload.get("project_root")
    if not isinstance(project_root, Path):
        return
    if event_type == "lifecycle.component.installed":
        apply_provider_surfaces(project_root)
    elif event_type == "lifecycle.component.uninstalled":
        prune_provider_surfaces(project_root)
        apply_provider_surfaces(project_root)


get_bus().subscribe("lifecycle.component.*", _on_component_lifecycle)
