"""Source control lifecycle observer.

Subscribes to lifecycle.component.* events on the foundation event bus.
On source-control install: installs the post-commit hook.
On source-control uninstall: removes the post-commit hook.

Self-registers when imported. Import is triggered by the source-control component
declaring lifecycle-observer in its YAML descriptor.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.event import get_bus

from .bootstrap import _install_post_commit_hook, _remove_post_commit_hook


def _on_component_lifecycle(event_type: str, payload: dict, metadata: dict) -> None:
    if payload.get("component_id") != "source-control":
        return
    project_root = payload.get("project_root")
    if not isinstance(project_root, Path):
        return
    if event_type == "lifecycle.component.installed":
        _install_post_commit_hook(project_root)
    elif event_type == "lifecycle.component.uninstalled":
        _remove_post_commit_hook(project_root)


get_bus().subscribe("lifecycle.component.*", _on_component_lifecycle)
