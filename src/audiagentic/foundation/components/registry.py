from __future__ import annotations

from pathlib import Path

from audiagentic.provisioning.home import audiagentic_home

from .base import SCOPE_HARNESS, ComponentDescriptor

_registry: dict[str, ComponentDescriptor] = {}


def register(descriptor: ComponentDescriptor) -> None:
    _registry[descriptor.component_id] = descriptor


def get_descriptor(component_id: str) -> ComponentDescriptor | None:
    return _registry.get(component_id)


def all_descriptors() -> dict[str, ComponentDescriptor]:
    return dict(_registry)


def component_root(descriptor: ComponentDescriptor, project_root: Path) -> Path:
    """Return the base directory for a component's files.

    Harness-scoped components resolve to audiagentic_home() so they are shared
    across all projects and are not tied to any single repo.
    """
    if descriptor.scope == SCOPE_HARNESS:
        return audiagentic_home()
    return project_root


def marker_path(component_id: str, root: Path, scope: str) -> Path:
    """Return the path to a component's installation marker file.

    Project scope:  root/.audiagentic/components/{id}.yaml
    Harness scope:  root/components/{id}.yaml  (root IS audiagentic_home())
    """
    if scope == SCOPE_HARNESS:
        return root / "components" / f"{component_id}.yaml"
    return root / ".audiagentic" / "components" / f"{component_id}.yaml"


def is_installed(component_id: str, project_root: Path) -> bool:
    descriptor = _registry.get(component_id)
    if descriptor is None:
        return False
    root = component_root(descriptor, project_root)
    return (root / descriptor.detection_marker).exists()


def is_enabled(component_id: str, project_root: Path) -> bool:
    descriptor = _registry.get(component_id)
    if descriptor is None:
        return True
    root = component_root(descriptor, project_root)
    mpath = marker_path(component_id, root, descriptor.scope)
    if not mpath.exists():
        return True
    try:
        import yaml
        data = yaml.safe_load(mpath.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return True
    return bool(data.get("enabled", True))
