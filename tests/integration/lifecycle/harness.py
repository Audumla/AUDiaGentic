from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml
from tests.helpers import sandbox as sandbox_helper

from audiagentic.foundation.components.base import MODE_CREATE_IF_MISSING, MODE_REQUIRED_MANAGED
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import all_descriptors, is_enabled, is_installed
from audiagentic.foundation.lifecycle.components import (
    disable_component,
    enable_component,
    install_component,
    uninstall_component,
)

register_all_components()
_CONFIG_PATH = Path(__file__).with_name("harness.yaml")


def _load_config() -> dict:
    data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"lifecycle harness config must be a mapping: {_CONFIG_PATH}")
    return data


HARNESS_CONFIG = _load_config()


def component_ids() -> list[str]:
    return sorted(all_descriptors().keys())


def project_component_ids() -> list[str]:
    selection = HARNESS_CONFIG.get("selection", {})
    scope = selection.get("scope", "project")
    exclude_core = bool(selection.get("exclude_core", True))
    result: list[str] = []
    for component_id in component_ids():
        descriptor = all_descriptors()[component_id]
        if descriptor.scope != scope:
            continue
        if exclude_core and descriptor.core:
            continue
        result.append(component_id)
    return result


def install_with_deps(component_id: str, project_root: Path) -> None:
    descriptor = all_descriptors()[component_id]
    for dep in descriptor.depends_on:
        if not is_installed(dep, project_root):
            install_with_deps(dep, project_root)
    if not is_installed(component_id, project_root):
        result = install_component(component_id, project_root)
        assert result.get("ok") is True, f"install failed for {component_id}: {result}"


@contextmanager
def component_sandbox(tmp_path: Path, name: str) -> Iterator[object]:
    sb = sandbox_helper.create(tmp_path, name)
    try:
        yield sb
    finally:
        sb.cleanup()


def marker_path(component_id: str, project_root: Path) -> Path:
    return project_root / ".audiagentic" / "components" / f"{component_id}.yaml"


def marker_data(component_id: str, project_root: Path) -> dict:
    path = marker_path(component_id, project_root)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def required_managed_paths(component_id: str, project_root: Path) -> list[Path]:
    descriptor = all_descriptors()[component_id]
    return [
        project_root / cf.rel_path
        for cf in descriptor.files
        if cf.lifecycle == MODE_REQUIRED_MANAGED and not cf.recursive
    ]


def create_if_missing_paths(component_id: str, project_root: Path) -> list[Path]:
    descriptor = all_descriptors()[component_id]
    return [
        project_root / cf.rel_path
        for cf in descriptor.files
        if cf.lifecycle == MODE_CREATE_IF_MISSING and not cf.recursive
    ]


def user_config_paths(component_id: str, project_root: Path) -> list[Path]:
    descriptor = all_descriptors()[component_id]
    return [
        project_root / cf.rel_path
        for cf in descriptor.files
        if cf.lifecycle == MODE_CREATE_IF_MISSING
        and cf.rel_path != descriptor.detection_marker
        and not cf.recursive
    ]


__all__ = [
    "all_descriptors",
    "component_ids",
    "component_sandbox",
    "create_if_missing_paths",
    "disable_component",
    "enable_component",
    "install_component",
    "install_with_deps",
    "is_enabled",
    "is_installed",
    "marker_data",
    "marker_path",
    "project_component_ids",
    "required_managed_paths",
    "uninstall_component",
    "user_config_paths",
]
