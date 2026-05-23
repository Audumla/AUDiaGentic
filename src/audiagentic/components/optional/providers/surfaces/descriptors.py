"""Load surface descriptors from YAML config files.

Surface descriptors define detection markers and file management rules
for provider surfaces. They are NOT top-level components — they are
managed by the providers component.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from audiagentic.paths import SRC_ROOT

_SURFACE_CONFIG_DIR = SRC_ROOT / "audiagentic" / "config" / "components" / "optional" / "providers"

_REGISTRY: dict[str, SurfaceDescriptor] = {}


@dataclass(frozen=True)
class SurfaceFile:
    rel_path: str
    lifecycle: str
    recursive: bool = False
    description: str = ""


@dataclass(frozen=True)
class SurfaceDescriptor:
    type: str
    descriptor_id: str
    display_name: str
    description: str
    detection_marker: str
    files: tuple[SurfaceFile, ...] = ()


def register_surface(descriptor: SurfaceDescriptor) -> None:
    _REGISTRY[descriptor.descriptor_id] = descriptor


def get_surface_descriptor(descriptor_id: str) -> SurfaceDescriptor | None:
    return _REGISTRY.get(descriptor_id)


def all_surfaces() -> dict[str, SurfaceDescriptor]:
    return dict(_REGISTRY)


def load_surface_from_yaml(path: Path) -> SurfaceDescriptor:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("type") != "provider":
        raise ValueError(f"{path.name}: expected type=provider, got {data.get('type')}")
    files = tuple(
        SurfaceFile(
            rel_path=f["path"],
            lifecycle=f["lifecycle"],
            recursive=bool(f.get("recursive", False)),
            description=f.get("description", ""),
        )
        for f in (data.get("files") or [])
    )
    descriptor = SurfaceDescriptor(
        type=data["type"],
        descriptor_id=data["id"],
        display_name=data.get("display-name", data["id"]),
        description=data.get("description", ""),
        detection_marker=data.get("detection-marker", ""),
        files=files,
    )
    register_surface(descriptor)
    return descriptor


def load_all_surfaces(config_dir: Path | None = None) -> list[SurfaceDescriptor]:
    target = (config_dir or _SURFACE_CONFIG_DIR).resolve()
    descriptors = []
    for path in sorted(target.rglob("*.yaml")):
        descriptors.append(load_surface_from_yaml(path))
    return descriptors
