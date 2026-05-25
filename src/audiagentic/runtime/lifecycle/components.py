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
from audiagentic.foundation.components.ids import COMPONENT_PROJECT
from audiagentic.foundation.components.registry import (
    all_descriptors,
    component_root,
    get_descriptor,
    is_installed,
    marker_path,
    resolve_component_id,
)
from audiagentic.runtime.harness.pi.install import build_runtime_sync

from .baseline_sync import sync_managed_baseline
from .observers import fire_post_disable, fire_post_enable, fire_post_install, fire_post_uninstall

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
    resolved = resolve_component_id(component_id) or component_id
    root = _get_component_root(component_id, project_root)
    scope = descriptor.scope if descriptor else "project"
    return marker_path(resolved, root, scope)


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
        "sync": build_runtime_sync(reason=reason, component_id=canonical_id),
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
    from threading import Thread

    from audiagentic.foundation.components.hooks import invoke_hook

    Thread(
        target=invoke_hook,
        args=(hook_path,),
        kwargs={"project_root": project_root, "failure_label": "post_install"},
        daemon=True,
    ).start()


def install_component(
    component_id: str,
    project_root: Path,
    *,
    source_root: Path | None = None,
    version: str = DEFAULT_VERSION,
    installation_kind: str | None = None,
    last_lifecycle_action: str | None = None,
) -> dict:
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
        )
    marker: dict = {
        "component-id": resolved_id,
        "enabled": True,
        "installed-at": _now_timestamp(),
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
    from audiagentic.foundation.components.hooks import get_component_status  # noqa: PLC0415
    status_payload = get_component_status(descriptor, project_root)
    if status_payload:
        result["component_status"] = status_payload
        missing = status_payload.get("missing-dependencies") or []
        follow_up = status_payload.get("follow_up")
        if isinstance(follow_up, dict):
            result["follow_up"] = follow_up
        if missing:
            install_offer = status_payload.get("dependency-install-offer", "")
            result["next-step"] = f"Missing: {', '.join(missing)}. {install_offer}".strip()
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
        mpath.unlink()
        if mpath not in deleted:
            deleted.append(mpath)
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
        deleted.extend(Path(path) for path in result.get("deleted", []) if isinstance(path, str))
    return deleted


def enable_component(component_id: str, project_root: Path) -> dict:
    resolved_id = resolve_component_id(component_id) or component_id
    if not is_installed(resolved_id, project_root):
        return {"ok": False, "error": f"component {component_id} is not installed"}
    data = _read_marker(resolved_id, project_root)
    data["component-id"] = resolved_id
    data["enabled"] = True
    _write_marker(resolved_id, project_root, data)
    fire_post_enable(resolved_id, project_root)
    return _component_result(resolved_id, reason="component-enabled", enabled=True)


def disable_component(component_id: str, project_root: Path) -> dict:
    resolved_id = resolve_component_id(component_id) or component_id
    if not is_installed(resolved_id, project_root):
        return {"ok": False, "error": f"component {component_id} is not installed"}
    data = _read_marker(resolved_id, project_root)
    data["component-id"] = resolved_id
    data["enabled"] = False
    _write_marker(resolved_id, project_root, data)
    fire_post_disable(resolved_id, project_root)
    return _component_result(resolved_id, reason="component-disabled", enabled=False)
