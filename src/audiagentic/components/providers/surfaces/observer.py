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

from functools import partial
from pathlib import Path

from audiagentic.foundation.event import get_bus, subscribe_component_lifecycle

from ..providers_api import operate_provider_surfaces
from ..services.mcp.mcp_projection import sync_component_mcp_to_providers


def _apply_surfaces(project_root: Path, payload: dict, metadata: dict) -> None:
    operate_provider_surfaces(project_root, mode="apply")


def _prune_then_apply_surfaces(project_root: Path, payload: dict, metadata: dict) -> None:
    operate_provider_surfaces(project_root, mode="prune")
    operate_provider_surfaces(project_root, mode="apply")


def _sync_component_mcp(
    project_root: Path, payload: dict, metadata: dict, *, enabled: bool
) -> None:
    sync_component_mcp_to_providers(payload["component_id"], project_root, enabled=enabled)


def _on_component_mcp_sync(event_type: str, payload: dict, metadata: dict) -> None:
    project_root = payload.get("project_root")
    component_id = payload.get("component_id")
    enabled = payload.get("enabled", True)
    if not isinstance(project_root, Path) or not isinstance(component_id, str):
        return
    sync_component_mcp_to_providers(component_id, project_root, enabled=bool(enabled))


# Dispatchers retained for tests exercising the event→action mapping.
_on_component_lifecycle = subscribe_component_lifecycle(
    None,
    on_installed=_apply_surfaces,
    on_enabled=_apply_surfaces,
    on_disabled=_prune_then_apply_surfaces,
    on_uninstalled=_prune_then_apply_surfaces,
)
_on_component_mcp_lifecycle = subscribe_component_lifecycle(
    None,
    on_installed=partial(_sync_component_mcp, enabled=True),
    on_enabled=partial(_sync_component_mcp, enabled=True),
    on_disabled=partial(_sync_component_mcp, enabled=False),
    on_uninstalled=partial(_sync_component_mcp, enabled=False),
    on_config_changed=partial(_sync_component_mcp, enabled=True),
)
get_bus().subscribe("lifecycle.component.mcp.sync", _on_component_mcp_sync)
