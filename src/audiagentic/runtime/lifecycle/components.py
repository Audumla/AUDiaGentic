"""Component-level lifecycle operations — install, uninstall, enable, disable."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from audiagentic.foundation.components.base import (
    MODE_CREATE_IF_MISSING,
    MODE_GENERATED_MANAGED,
    MODE_REQUIRED_MANAGED,
    MODE_RUNTIME_ONLY,  # uninstall logic only
)
from audiagentic.foundation.components.registry import (
    all_descriptors,
    component_root,
    get_descriptor,
    is_installed,
    marker_path,
)

from .baseline_sync import sync_managed_baseline

_REMOVE_ALWAYS = {MODE_REQUIRED_MANAGED, MODE_GENERATED_MANAGED, MODE_RUNTIME_ONLY}
_REMOVE_WITH_CONFIGS = {MODE_CREATE_IF_MISSING}

DEFAULT_VERSION = "0.1.0"


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_component_root(component_id: str, project_root: Path) -> Path:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return project_root
    return component_root(descriptor, project_root)


def _get_marker_path(component_id: str, project_root: Path) -> Path:
    descriptor = get_descriptor(component_id)
    root = _get_component_root(component_id, project_root)
    scope = descriptor.scope if descriptor else "project"
    return marker_path(component_id, root, scope)


def _read_marker(component_id: str, project_root: Path) -> dict:
    path = _get_marker_path(component_id, project_root)
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _write_marker(component_id: str, project_root: Path, data: dict) -> None:
    path = _get_marker_path(component_id, project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=True), encoding="utf-8")


def get_owned_files(
    component_id: str,
    project_root: Path,
    *,
    lifecycle: str | None = None,
) -> list[Path]:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return []
    root = component_root(descriptor, project_root)
    results: list[Path] = []
    for cf in descriptor.files:
        if lifecycle is not None and cf.lifecycle != lifecycle:
            continue
        target = root / cf.rel_path
        if cf.recursive:
            if target.exists() and target.is_dir():
                results.extend(sorted(p for p in target.rglob("*") if p.is_file()))
        else:
            if target.exists():
                results.append(target)
    return results


def install_component(
    component_id: str,
    project_root: Path,
    *,
    source_root: Path | None = None,
    version: str = DEFAULT_VERSION,
    installation_kind: str | None = None,
    last_lifecycle_action: str | None = None,
) -> dict:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown component: {component_id}"}
    root = component_root(descriptor, project_root)
    # Harness-scoped components have no template files to sync
    report: dict = {}
    if descriptor.scope != "harness":
        report = sync_managed_baseline(
            project_root,
            source_root=source_root,
            component_ids={component_id},
        )
    marker: dict = {
        "component-id": component_id,
        "enabled": True,
        "installed-at": _now_timestamp(),
        "version": version,
    }
    if component_id == "core-lifecycle":
        marker["installation-kind"] = installation_kind or "fresh"
        marker["last-lifecycle-action"] = last_lifecycle_action or "fresh-install"
    _write_marker(component_id, project_root, marker)
    return {"ok": True, "component_id": component_id, "root": str(root), "sync": report}


def uninstall_component(
    component_id: str,
    project_root: Path,
    *,
    remove_configs: bool = False,
) -> list[Path]:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return []
    root = component_root(descriptor, project_root)
    deleted: list[Path] = []
    for cf in descriptor.files:
        remove = cf.lifecycle in _REMOVE_ALWAYS or (
            remove_configs and cf.lifecycle in _REMOVE_WITH_CONFIGS
        )
        if not remove:
            continue
        target = root / cf.rel_path
        if cf.recursive:
            if target.exists() and target.is_dir():
                shutil.rmtree(target)
                deleted.append(target)
        else:
            if target.exists():
                target.unlink()
                deleted.append(target)
    # Always remove the marker — it is system-owned, not user config
    mpath = _get_marker_path(component_id, project_root)
    if mpath.exists():
        mpath.unlink()
        if mpath not in deleted:
            deleted.append(mpath)
    return deleted


def uninstall_all_components(
    project_root: Path,
    *,
    remove_configs: bool = False,
) -> list[Path]:
    deleted: list[Path] = []
    for component_id in all_descriptors():
        deleted.extend(uninstall_component(component_id, project_root, remove_configs=remove_configs))
    return deleted


def enable_component(component_id: str, project_root: Path) -> dict:
    if not is_installed(component_id, project_root):
        return {"ok": False, "error": f"component {component_id} is not installed"}
    data = _read_marker(component_id, project_root)
    data["component-id"] = component_id
    data["enabled"] = True
    _write_marker(component_id, project_root, data)
    return {"ok": True, "component_id": component_id, "enabled": True}


def disable_component(component_id: str, project_root: Path) -> dict:
    if not is_installed(component_id, project_root):
        return {"ok": False, "error": f"component {component_id} is not installed"}
    data = _read_marker(component_id, project_root)
    data["component-id"] = component_id
    data["enabled"] = False
    _write_marker(component_id, project_root, data)
    return {"ok": True, "component_id": component_id, "enabled": False}
