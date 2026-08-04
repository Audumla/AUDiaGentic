"""Public API surface for the core project component."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.components.registry import is_enabled, is_installed
from audiagentic.foundation.features.registry import all_features, all_implementations
from audiagentic.foundation.features.resolver import resolve_feature, resolve_implementation

from . import project_components, project_files, project_surfaces


def project_status(project_root: Path) -> dict[str, Any]:
    """Return project installation state and component details."""
    return project_components.project_status(project_root)


def list_components(project_root: Path) -> list[dict[str, Any]]:
    """List all known components and current install state."""
    return project_components.list_components(project_root)


def install_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Install a component and refresh generated harness config when needed."""
    return project_components.install_component(project_root, component_id)


def uninstall_component(
    project_root: Path, component_id: str, *, remove_configs: bool = False
) -> dict[str, Any]:
    """Uninstall a non-core component and refresh generated harness config."""
    return project_components.uninstall_component(
        project_root, component_id, remove_configs=remove_configs
    )


def enable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Enable a component and refresh generated harness config."""
    return project_components.enable_component(project_root, component_id)


def disable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Disable a component and refresh generated harness config."""
    return project_components.disable_component(project_root, component_id)


def read_project_file(project_root: Path, relative_path: str) -> dict[str, Any]:
    """Read a file under the managed project `.audiagentic` tree."""
    return project_files.read_project_file(project_root, relative_path)


def list_project_instructions(project_root: Path) -> list[dict[str, Any]]:
    return project_surfaces.list_project_instructions(project_root)

def get_project_instruction(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.get_project_instruction(project_root, item_id)

def create_project_instruction(project_root: Path, item_id: str, title: str, body: str, preferred_targets: list[str] | None = None) -> dict[str, Any]:
    return project_surfaces.create_project_instruction(project_root, item_id, title, body, preferred_targets)

def update_project_instruction(project_root: Path, item_id: str, title: str | None = None, body: str | None = None, preferred_targets: list[str] | None = None) -> dict[str, Any]:
    return project_surfaces.update_project_instruction(project_root, item_id, title, body, preferred_targets)

def delete_project_instruction(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.delete_project_instruction(project_root, item_id)

def list_project_skills(project_root: Path) -> list[dict[str, Any]]:
    return project_surfaces.list_project_skills(project_root)

def get_project_skill(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.get_project_skill(project_root, item_id)

def create_project_skill(project_root: Path, item_id: str, content: str) -> dict[str, Any]:
    return project_surfaces.create_project_skill(project_root, item_id, content)

def update_project_skill(project_root: Path, item_id: str, content: str) -> dict[str, Any]:
    return project_surfaces.update_project_skill(project_root, item_id, content)

def delete_project_skill(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.delete_project_skill(project_root, item_id)


def runtime_sync_contract() -> dict[str, Any]:
    """Describe the runtime-sync contract expected by Pi runtime clients."""
    from audiagentic.foundation.capabilities import get_harness_status

    hs = get_harness_status()
    return {
        "target": "pi-runtime",
        "actions": {
            "refresh_required": "Refresh local client state only.",
            "reload_required": "Reload Pi runtime after request completes.",
            "restart_required": "Prompt for full Pi session restart.",
        },
        "example": hs["build_runtime_sync"](
            reason="component-installed", component_id="providers"
        ),  # cross-component example payload,
    }


def get_option_provenance(
    project_root: Path,
    component_id: str | None = None,
) -> dict[str, Any]:
    """Return option provenance for all features and implementations.

    For each feature/implementation, shows which layer provided each option value.
    Source values: 'schema-default', 'component-state', 'feature-state', 'implementation-state'.

    If component_id is provided, only returns provenance for that component.
    """
    results: dict[str, list[dict[str, Any]]] = {"features": [], "implementations": []}

    for key, descriptor in all_features().items():
        if component_id and descriptor.parent != component_id:
            continue
        if not is_installed(descriptor.parent, project_root):
            continue
        if not is_enabled(descriptor.parent, project_root):
            continue
        resolved = resolve_feature(project_root, descriptor)
        if resolved.option_provenance:
            results["features"].append(
                {
                    "parent": descriptor.parent,
                    "kind": descriptor.kind,
                    "feature_id": descriptor.feature_id,
                    "provenance": {
                        k: {"value": v.value, "source": v.source}
                        for k, v in resolved.option_provenance.items()
                    },
                }
            )

    for key, descriptor in all_implementations().items():
        if component_id and descriptor.parent != component_id:
            continue
        if not is_installed(descriptor.parent, project_root):
            continue
        if not is_enabled(descriptor.parent, project_root):
            continue
        resolved = resolve_implementation(project_root, descriptor)
        if resolved.option_provenance:
            results["implementations"].append(
                {
                    "parent": descriptor.parent,
                    "implementation_id": descriptor.implementation_id,
                    "provenance": {
                        k: {"value": v.value, "source": v.source}
                        for k, v in resolved.option_provenance.items()
                    },
                }
            )

    return results
