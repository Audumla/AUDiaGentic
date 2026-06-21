"""Provider surface lifecycle observer.

Subscribes to lifecycle.component.* events on the foundation event bus.
On component install or enable: applies surface contributions for all installed providers.
On component uninstall or disable: prunes stale blocks then re-applies remaining contributions.

This module self-registers when imported. Import is triggered by the providers component
declaring lifecycle-observer in its YAML descriptor, which causes register_all_components()
to import this module after loading descriptors.

Neither this module nor the lifecycle layer know about each other directly —
decoupled via the event bus.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.event import get_bus

from ..services.lsp_projection import (
    CODING_LSP_PROVIDER_PROJECTION,
    handle_lsp_provider_projection,
)
from ..services.mcp_projection import sync_component_mcp_to_providers
from .manager import apply_provider_surfaces, prune_provider_surfaces


def _on_component_lifecycle(event_type: str, payload: dict, metadata: dict) -> None:
    project_root = payload.get("project_root")
    if not isinstance(project_root, Path):
        return
    if event_type in ("lifecycle.component.installed", "lifecycle.component.enabled"):
        apply_provider_surfaces(project_root)
    elif event_type in ("lifecycle.component.uninstalled", "lifecycle.component.disabled"):
        prune_provider_surfaces(project_root)
        apply_provider_surfaces(project_root)


def _on_component_mcp_lifecycle(event_type: str, payload: dict, metadata: dict) -> None:
    project_root = payload.get("project_root")
    component_id = payload.get("component_id")
    if not isinstance(project_root, Path) or not isinstance(component_id, str):
        return
    enabled = event_type != "lifecycle.component.uninstalled"
    sync_component_mcp_to_providers(component_id, project_root, enabled=enabled)


def _on_component_mcp_sync(event_type: str, payload: dict, metadata: dict) -> None:
    project_root = payload.get("project_root")
    component_id = payload.get("component_id")
    enabled = payload.get("enabled", True)
    if not isinstance(project_root, Path) or not isinstance(component_id, str):
        return
    sync_component_mcp_to_providers(component_id, project_root, enabled=bool(enabled))


get_bus().subscribe("lifecycle.component.*", _on_component_lifecycle)
get_bus().subscribe("lifecycle.component.*", _on_component_mcp_lifecycle)
get_bus().subscribe("lifecycle.component.mcp.sync", _on_component_mcp_sync)
get_bus().subscribe(CODING_LSP_PROVIDER_PROJECTION, handle_lsp_provider_projection)
