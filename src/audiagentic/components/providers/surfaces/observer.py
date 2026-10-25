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

from audiagentic.foundation.event import subscribe_component_lifecycle

from ..providers_api import operate_provider_surfaces


def _apply_surfaces(project_root: Path, payload: dict, metadata: dict) -> None:
    operate_provider_surfaces(project_root, mode="apply")


def _prune_then_apply_surfaces(project_root: Path, payload: dict, metadata: dict) -> None:
    operate_provider_surfaces(project_root, mode="prune")
    operate_provider_surfaces(project_root, mode="apply")


# Dispatchers retained for tests exercising the event→action mapping.
_on_component_lifecycle = subscribe_component_lifecycle(
    None,
    on_installed=_apply_surfaces,
    on_enabled=_apply_surfaces,
    on_disabled=_prune_then_apply_surfaces,
    on_uninstalled=_prune_then_apply_surfaces,
)
