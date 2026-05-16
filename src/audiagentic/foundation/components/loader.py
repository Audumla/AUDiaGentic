"""Load and register ComponentDescriptors from YAML config files."""
from __future__ import annotations

from pathlib import Path

from audiagentic.paths import SRC_ROOT

from .base import ComponentDescriptor, ComponentFile
from .registry import register

_COMPONENTS_CONFIG_DIR = SRC_ROOT / "audiagentic" / "config" / "foundation" / "components"
_PROVIDER_SURFACES_CONFIG_DIR = SRC_ROOT / "audiagentic" / "config" / "interoperability" / "providers" / "surfaces"
_ALL_COMPONENT_CONFIG_DIRS = [_COMPONENTS_CONFIG_DIR, _PROVIDER_SURFACES_CONFIG_DIR]


def register_from_yaml(path: Path) -> ComponentDescriptor:
    """Parse a single component config YAML and register the descriptor."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    files = tuple(
        ComponentFile(
            rel_path=f["path"],
            lifecycle=f["lifecycle"],
            recursive=bool(f.get("recursive", False)),
            description=f.get("description", ""),
        )
        for f in (data.get("files") or [])
    )
    descriptor = ComponentDescriptor(
        component_id=data["component-id"],
        display_name=data.get("display-name", data["component-id"]),
        description=data.get("description", ""),
        detection_marker=data["detection-marker"],
        files=files,
        depends_on=tuple(data.get("depends-on") or []),
        config_path=data.get("config") or None,
    )
    register(descriptor)
    return descriptor


def register_all_components(config_dirs: list[Path] | None = None) -> list[ComponentDescriptor]:
    """Load and register every *.yaml file across all component config dirs.

    Defaults to foundation/components and interoperability/providers/surfaces.
    Idempotent — re-registering an already-known component-id is a no-op overwrite.
    """
    targets = config_dirs or _ALL_COMPONENT_CONFIG_DIRS
    descriptors = []
    for target in targets:
        for path in sorted(target.resolve().rglob("*.yaml")):
            descriptors.append(register_from_yaml(path))
    return descriptors
