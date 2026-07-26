"""Component status and lifecycle helpers for the core project component."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.components import all_descriptors, is_enabled, is_installed
from audiagentic.foundation.components.hooks import get_component_status
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.lifecycle.components import (
    disable_component as _lifecycle_disable_component,
)
from audiagentic.foundation.lifecycle.components import (
    enable_component as _lifecycle_enable_component,
)
from audiagentic.foundation.lifecycle.components import (
    install_component as _lifecycle_install_component,
)
from audiagentic.foundation.lifecycle.components import (
    uninstall_component as _lifecycle_uninstall_component,
)
from audiagentic.foundation.lifecycle.detector import (
    detect_installed_state,
    get_project_version_info,
)


def project_status(project_root: Path) -> dict[str, Any]:
    state = detect_installed_state(project_root)
    component_details: dict[str, dict[str, Any]] = {}
    for component_id, descriptor in all_descriptors().items():
        if not is_installed(component_id, project_root):
            continue
        payload = get_component_status(descriptor, project_root)
        if payload is not None:
            component_details[component_id] = payload
    return {
        "project_root": str(project_root),
        "install_state": state.state,
        "audiagentic_markers": state.audiagentic_markers,
        "components": component_status_index(project_root),
        "version_info": get_project_version_info(project_root)
        if state.state == "installed"
        else None,
        "component_details": component_details,
    }


def list_components(project_root: Path) -> list[dict[str, Any]]:
    return [component_row(descriptor, project_root) for descriptor in all_descriptors().values()]


def install_component(project_root: Path, component_id: str) -> dict[str, Any]:
    result = _lifecycle_install_component(component_id, project_root)
    return attach_harness_refresh(result, project_root)


def uninstall_component(
    project_root: Path, component_id: str, *, remove_configs: bool = False
) -> dict[str, Any]:
    descriptor = all_descriptors().get(component_id)
    if descriptor and descriptor.core:
        raise AudiaGenticError(
            code="CON-PROJCOMP-001",
            kind="project",
            message="cannot uninstall core component",
            details={"component-id": component_id},
        )
    result = _lifecycle_uninstall_component(
        component_id, project_root, remove_configs=remove_configs
    )
    return attach_harness_refresh(result, project_root)


def enable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    result = _lifecycle_enable_component(component_id, project_root)
    return attach_harness_refresh(result, project_root)


def disable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    result = _lifecycle_disable_component(component_id, project_root)
    return attach_harness_refresh(result, project_root)


def component_status_index(project_root: Path) -> dict[str, dict[str, Any]]:
    return {
        component_id: {
            "status": "installed" if is_installed(component_id, project_root) else "not-installed",
            "enabled": is_enabled(component_id, project_root)
            if is_installed(component_id, project_root)
            else False,
        }
        for component_id in all_descriptors()
    }


def component_row(descriptor, project_root: Path) -> dict[str, Any]:
    installed = is_installed(descriptor.component_id, project_root)
    row = {
        "component_id": descriptor.component_id,
        "display_name": descriptor.display_name,
        "description": descriptor.description,
        "status": "installed" if installed else "not-installed",
        "enabled": is_enabled(descriptor.component_id, project_root) if installed else False,
        "core": descriptor.core,
        "detection_marker": descriptor.detection_marker,
        "file_count": len(descriptor.files),
    }
    if installed:
        payload = get_component_status(descriptor, project_root)
        if payload is not None:
            row["component_status"] = payload
    return row


def attach_harness_refresh(
    result: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Report harness availability without re-running the harness refresh.

    The lifecycle event this follows (component-installed/enabled/disabled/
    uninstalled) already triggered runtime.harness's own synchronous refresh
    via its component-lifecycle subscription (runtime/harness/__init__.py) --
    calling refresh_harness_config_if_installed here too would just repeat
    that work a second time for every action.
    """
    if not result.get("ok", True):
        return result
    from audiagentic.foundation.capabilities import get_harness_status

    hs = get_harness_status()
    harness_type = hs["get_harness_type"](project_root)
    harness_available = hs["harness_cli_available"](harness_type) is not None
    return {**result, "harness_available": harness_available}
