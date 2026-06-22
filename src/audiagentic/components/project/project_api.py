"""Public API surface for the core project component."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.runtime.harness import build_runtime_sync

from . import project_components, project_files


def project_status(project_root: Path) -> dict[str, Any]:
    """Return project installation state and component details."""
    return project_components.project_status(project_root)


def list_components(project_root: Path) -> list[dict[str, Any]]:
    """List all known components and current install state."""
    return project_components.list_components(project_root)


def install_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Install a component and refresh generated harness config when needed."""
    return project_components.install_component(project_root, component_id)


def uninstall_component(project_root: Path, component_id: str, *, remove_configs: bool = False) -> dict[str, Any]:
    """Uninstall a non-core component and refresh generated harness config."""
    return project_components.uninstall_component(project_root, component_id, remove_configs=remove_configs)


def enable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Enable a component and refresh generated harness config."""
    return project_components.enable_component(project_root, component_id)


def disable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Disable a component and refresh generated harness config."""
    return project_components.disable_component(project_root, component_id)


def read_project_file(project_root: Path, relative_path: str) -> dict[str, Any]:
    """Read a file under the managed project `.audiagentic` tree."""
    return project_files.read_project_file(project_root, relative_path)


def runtime_sync_contract() -> dict[str, Any]:
    """Describe the runtime-sync contract expected by Pi runtime clients."""
    return {
        "target": "pi-runtime",
        "actions": {
            "refresh_required": "Refresh local client state only.",
            "reload_required": "Reload Pi runtime after request completes.",
            "restart_required": "Prompt for full Pi session restart.",
        },
        "example": build_runtime_sync(reason="component-installed", component_id=COMPONENT_PROVIDERS),
    }
