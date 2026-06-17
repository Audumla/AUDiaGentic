"""Component-level lifecycle operations — install, uninstall, enable, disable."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

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
from audiagentic.runtime.config import load_yaml_file, save_yaml_file
from audiagentic.runtime.harness import build_runtime_sync

from .baseline_sync import sync_managed_baseline
from .observers import fire_post_disable, fire_post_enable, fire_post_install, fire_post_uninstall

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


def _read_marker(component_id: str, project_root: Path) -> dict:
    path = _get_marker_path(component_id, project_root)
    try:
        return load_yaml_file(path)
    except Exception:
        logger.warning("Failed to read marker for %s", component_id, exc_info=True)
        return {}


def _write_marker(component_id: str, project_root: Path, data: dict) -> None:
    path = _get_marker_path(component_id, project_root)
    save_yaml_file(path, data, sort_keys=True)


def _component_result(
    component_id: str,
    *,
    reason: str,
    **payload: object,
) -> dict[str, object]:
    canonical_id = resolve_component_id(component_id) or component_id
    descriptor = get_descriptor(canonical_id)
    has_mcp = bool(
        descriptor and (descriptor.mcp_servers or descriptor.external_mcp_servers)
    )
    return {
        "ok": True,
        "component_id": canonical_id,
        "sync": build_runtime_sync(reason=reason, component_id=canonical_id, has_mcp_servers=has_mcp, target="project"),
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
    _refresh_mcp_config_if_needed(descriptor, project_root, reason="component-installed")
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
    _refresh_mcp_config_if_needed(descriptor, project_root, reason="component-uninstalled")
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
    descriptor = get_descriptor(component_id)
    data = _read_marker(resolved_id, project_root)
    data["component-id"] = resolved_id
    data["enabled"] = True
    _write_marker(resolved_id, project_root, data)
    fire_post_enable(resolved_id, project_root)
    _refresh_mcp_config_if_needed(descriptor, project_root, reason="component-enabled")
    return _component_result(resolved_id, reason="component-enabled", enabled=True)


def disable_component(component_id: str, project_root: Path) -> dict:
    resolved_id = resolve_component_id(component_id) or component_id
    if not is_installed(resolved_id, project_root):
        return {"ok": False, "error": f"component {component_id} is not installed"}
    descriptor = get_descriptor(component_id)
    data = _read_marker(resolved_id, project_root)
    data["component-id"] = resolved_id
    data["enabled"] = False
    _write_marker(resolved_id, project_root, data)
    fire_post_disable(resolved_id, project_root)
    _refresh_mcp_config_if_needed(descriptor, project_root, reason="component-disabled")
    return _component_result(resolved_id, reason="component-disabled", enabled=False)


def _refresh_mcp_config_if_needed(descriptor, project_root: Path, *, reason: str) -> None:
    """Refresh harness MCP config and propagate to providers if component declares MCP servers."""
    if not descriptor.mcp_servers and not descriptor.external_mcp_servers:
        return
    try:
        from audiagentic.runtime.harness import refresh_harness_config_if_installed
        refresh_harness_config_if_installed(
            project_root,
            reason=reason,
            component_id=descriptor.component_id,
        )
    except Exception:
        logger.warning("Failed to refresh harness config for %s", descriptor.component_id, exc_info=True)
    try:
        _propagate_mcp_to_providers(descriptor, project_root)
    except Exception:
        logger.warning("Failed to propagate MCP config for %s", descriptor.component_id, exc_info=True)


def _propagate_mcp_to_providers(descriptor, project_root: Path) -> None:
    """Add/remove component MCP servers on every provider that has mcp_config defined.

    Servers with propagate containing "providers" are added.
    Servers with propagate not containing "providers" are pruned (removes stale entries).
    """
    import importlib
    import sys

    importlib.import_module("audiagentic.components.optional.providers")
    from audiagentic.components.optional.providers.descriptors.registry import all_descriptors
    from audiagentic.components.optional.providers.services.mcp import sync_managed_provider_mcp
    from audiagentic.runtime.harness.paths import find_package_root

    python = sys.executable.replace("\\", "/")
    src_dir = str(find_package_root(Path(__file__)).parent).replace("\\", "/")

    providers = all_descriptors()
    for provider_id, pdesc in providers.items():
        if pdesc.mcp_config is None:
            continue
        desired_entries: dict[str, tuple[str, object]] = {}
        for mcp_def in (descriptor.mcp_servers or []):
            if "providers" in mcp_def.propagate:
                # Native LSP supersedes the generic MCP LSP server: skip this
                # server for providers that manage their own language servers.
                if getattr(mcp_def, "skip_if_native_lsp", False) and pdesc.language_servers_config is not None:
                    continue
                from audiagentic.foundation.mcp import McpServerEntry

                managed_id = mcp_def.managed_id or mcp_def.name
                desired_entries[managed_id] = (
                    mcp_def.name,
                    McpServerEntry(
                        name=mcp_def.name,
                        command=python,
                        args=("-m", mcp_def.module) + tuple(mcp_def.args),
                        env={"PYTHONPATH": src_dir},
                    ),
                )
        for mcp_def in (descriptor.external_mcp_servers or []):
            if "providers" in mcp_def.propagate:
                from audiagentic.foundation.mcp import McpServerEntry

                managed_id = mcp_def.managed_id or mcp_def.name
                desired_entries[managed_id] = (
                    mcp_def.name,
                    McpServerEntry(
                        name=mcp_def.name,
                        command=mcp_def.command,
                        args=tuple(mcp_def.args),
                        env=dict(mcp_def.env) if mcp_def.env else {},
                    ),
                )
        sync_managed_provider_mcp(provider_id=provider_id, project_root=project_root, desired_entries=desired_entries)


def sync_all_provider_mcp_servers(project_root: Path) -> None:
    """Reconcile MCP servers across all provider configs for all installed+enabled components.

    Adds servers with propagate containing "providers" and removes servers that
    are known but not meant for providers. Safe to call at any time — converges
    to the correct state regardless of prior history.
    """
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import is_enabled

    register_all_components()
    for component_id, descriptor in all_descriptors().items():
        if not descriptor.mcp_servers and not descriptor.external_mcp_servers:
            continue
        if not descriptor.core and not is_installed(component_id, project_root):
            continue
        if not descriptor.core and not is_enabled(component_id, project_root):
            continue
        try:
            _propagate_mcp_to_providers(descriptor, project_root)
        except Exception:
            logger.warning("Failed to sync MCP servers for %s", component_id, exc_info=True)
