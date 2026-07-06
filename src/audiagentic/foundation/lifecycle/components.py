"""Component-level lifecycle operations — install, uninstall, enable, disable."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, cast

from audiagentic.foundation.components.base import (
    MODE_CREATE_IF_MISSING,
    MODE_GENERATED_MANAGED,
    MODE_REQUIRED_MANAGED,
    MODE_RUNTIME_ONLY,  # uninstall logic only
)
from audiagentic.foundation.components.hooks import get_component_status, invoke_hook
from audiagentic.foundation.components.ids import COMPONENT_PROJECT
from audiagentic.foundation.components.registry import (
    all_descriptors,
    component_root,
    get_descriptor,
    is_installed,
    marker_path,
    resolve_component_id,
)
from audiagentic.foundation.io import load_yaml_file, save_yaml_file
from audiagentic.foundation.time import now_iso_z

# Local imports (relative to lifecycle package)
from .baseline_sync import sync_managed_baseline
from .observers import fire_post_disable, fire_post_enable, fire_post_install, fire_post_uninstall

logger = logging.getLogger(__name__)

_REMOVE_ALWAYS = {MODE_REQUIRED_MANAGED, MODE_GENERATED_MANAGED, MODE_RUNTIME_ONLY}
_REMOVE_WITH_CONFIGS = {MODE_CREATE_IF_MISSING}

DEFAULT_VERSION = "0.1.0"


def _get_component_root(component_id: str, project_root: Path) -> Path:
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return project_root
    return component_root(descriptor, project_root)


def _get_marker_path(component_id: str, project_root: Path) -> Path:
    descriptor = get_descriptor(component_id)
    resolved = resolve_component_id(component_id) or component_id
    root = _get_component_root(component_id, project_root)
    scope = descriptor.scope if descriptor else "project"
    return marker_path(resolved, root, scope)


def _read_marker(component_id: str, project_root: Path) -> dict[str, Any]:
    path = _get_marker_path(component_id, project_root)
    try:
        return load_yaml_file(path)
    except Exception:
        logger.warning("Failed to read marker for %s", component_id, exc_info=True, extra={"component": component_id})
        return {}


def _write_marker(component_id: str, project_root: Path, data: dict[str, Any]) -> None:
    path = _get_marker_path(component_id, project_root)
    save_yaml_file(path, data, sort_keys=True)


def _component_result(
    component_id: str,
    *,
    reason: str,
    **payload: object,
) -> dict[str, object]:
    canonical_id = resolve_component_id(component_id) or component_id
    return {
        "ok": True,
        "component_id": canonical_id,
        **payload,
    }


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


def _resolve_and_run_post_install(hook_path: str, project_root: Path) -> None:
    invoke_hook(hook_path, project_root=project_root, failure_label="post_install")


def install_component(
    component_id: str,
    project_root: Path,
    *,
    source_root: Path | None = None,
    version: str = DEFAULT_VERSION,
    installation_kind: str | None = None,
    last_lifecycle_action: str | None = None,
    lifecycle_modes: set[str] | None = None,
) -> dict[str, object]:
    resolved_id = resolve_component_id(component_id) or component_id
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
            lifecycle_modes=lifecycle_modes,
            refresh_overrides=True,
        )
    marker: dict[str, Any] = {
        "component-id": resolved_id,
        "enabled": True,
        "installed-at": now_iso_z(),
        "version": version,
    }
    if resolved_id == COMPONENT_PROJECT:
        marker["installation-kind"] = installation_kind or "fresh"
        marker["last-lifecycle-action"] = last_lifecycle_action or "fresh-install"
    _write_marker(resolved_id, project_root, marker)
    if descriptor.post_install:
        _resolve_and_run_post_install(descriptor.post_install, project_root)

    fire_post_install(resolved_id, project_root)
    result = _component_result(
        resolved_id,
        reason="component-installed",
        root=str(root),
        baseline_sync=report,
    )
    status_payload = get_component_status(descriptor, project_root)
    if status_payload:
        result["component_status"] = status_payload
        details = status_payload.get("details") or {}
        missing = details.get("missing_dependencies") or []
        if follow_up := details.get("follow_up"):
            if isinstance(follow_up, dict):
                result["follow_up"] = follow_up
        if missing:
            offer = details.get("dependency_install_offer", "")
            result["next-step"] = f"Missing: {', '.join(missing)}. {offer}".strip()
    return result


def uninstall_component(
    component_id: str,
    project_root: Path,
    *,
    remove_configs: bool = False,
) -> dict[str, object]:
    resolved_id = resolve_component_id(component_id) or component_id
    descriptor = get_descriptor(component_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown component: {component_id}"}
    if descriptor.core:
        return {"ok": False, "error": f"cannot uninstall core component: {resolved_id}"}
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
    mpath = _get_marker_path(resolved_id, project_root)
    if mpath.exists():
        deleted.append(mpath)
        mpath.unlink()
    fire_post_uninstall(resolved_id, project_root)
    return _component_result(
        resolved_id,
        reason="component-uninstalled",
        root=str(root),
        deleted=[str(path) for path in deleted],
        removed_configs=bool(remove_configs),
    )


def uninstall_all_components(
    project_root: Path,
    *,
    remove_configs: bool = False,
) -> list[Path]:
    deleted: list[Path] = []
    for component_id in all_descriptors():
        result = uninstall_component(component_id, project_root, remove_configs=remove_configs)
        deleted.extend(Path(p) for p in cast(list[str], result.get("deleted") or []) if isinstance(p, str))
    return deleted


def _toggle_component(component_id: str, project_root: Path, *, enabled: bool, event_fn, reason_suffix: str) -> dict[str, object]:
    resolved_id = resolve_component_id(component_id) or component_id
    if not is_installed(resolved_id, project_root):
        return {"ok": False, "error": f"component {component_id} is not installed"}
    data = _read_marker(resolved_id, project_root)
    data["component-id"] = resolved_id
    data["enabled"] = enabled
    _write_marker(resolved_id, project_root, data)
    event_fn(resolved_id, project_root)
    return _component_result(resolved_id, reason=f"component-{reason_suffix}", enabled=enabled)


def enable_component(component_id: str, project_root: Path) -> dict[str, object]:
    return _toggle_component(component_id, project_root, enabled=True, event_fn=fire_post_enable, reason_suffix="enabled")


def disable_component(component_id: str, project_root: Path) -> dict[str, object]:
    return _toggle_component(component_id, project_root, enabled=False, event_fn=fire_post_disable, reason_suffix="disabled")
