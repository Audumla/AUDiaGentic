from __future__ import annotations

from pathlib import Path

from .base import ComponentDescriptor

_registry: dict[str, ComponentDescriptor] = {}


def register(descriptor: ComponentDescriptor) -> None:
    _registry[descriptor.component_id] = descriptor


def get_descriptor(component_id: str) -> ComponentDescriptor | None:
    return _registry.get(component_id)


def all_descriptors() -> dict[str, ComponentDescriptor]:
    return dict(_registry)


def is_installed(component_id: str, project_root: Path) -> bool:
    descriptor = _registry.get(component_id)
    if descriptor is None:
        return False
    return (project_root / descriptor.detection_marker).exists()


def is_enabled(component_id: str, project_root: Path) -> bool:
    marker_path = project_root / ".audiagentic" / "components" / f"{component_id}.yaml"
    if not marker_path.exists():
        return True
    try:
        import yaml
        data = yaml.safe_load(marker_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return True
    return bool(data.get("enabled", True))
