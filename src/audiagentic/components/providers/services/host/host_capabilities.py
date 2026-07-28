"""Host-capability (editor extension) status derivation.

All host-specific filesystem access routes through the host adapter
(services/host_adapter.py); this module holds no editor path literals.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, to_error_envelope

from ...descriptors.base import HostCapability
from .host_adapter import get_host_adapter


def list_installed_extensions(host_id: str = "vscode", *, allow_probe: bool = True) -> list[str] | None:
    """Return installed extension IDs for a host without spawning it."""
    return get_host_adapter(host_id).installed_extension_ids(allow_probe=allow_probe)


def host_workspace_detected(project_root: Path, host_id: str) -> bool:
    return get_host_adapter(host_id).detect_workspace(project_root)


def host_extension_status(
    ext: HostCapability,
    *,
    workspace: bool,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "host": ext.host,
        "capability_id": ext.capability_id,
        "extension_id": ext.capability_id,
        "display_name": ext.display_name,
        "applicable": workspace,
        "installed": None,
    }
    if not workspace:
        return entry
    adapter = get_host_adapter(ext.host)
    installed_list = adapter.installed_extension_ids()
    if installed_list is None:
        entry["error"] = to_error_envelope(
            AudiaGenticError(
                code="CFG-PVEXT-001",
                kind="providers",
                message=f"{adapter.display_name or ext.host} extension state unavailable",
                details={
                    "extension-id": ext.capability_id,
                    "source": f"{ext.host}-extension-probe",
                    "path": str(adapter.extension_dir()),
                },
            )
        )
    else:
        entry["installed"] = ext.capability_id.lower() in installed_list
    return entry


def host_extension_statuses(
    project_root: Path,
    extensions: tuple[HostCapability, ...],
) -> tuple[dict[str, bool], list[dict[str, Any]]]:
    """Return ({host_id: workspace-detected}, per-extension status entries).

    Workspace detection covers every host referenced by ``extensions`` plus
    every configured host, so callers can report hosts with no capabilities.
    """
    from .host_adapter import all_host_adapters

    hosts = {
        host_id: adapter.detect_workspace(project_root)
        for host_id, adapter in all_host_adapters().items()
    }
    for ext in extensions:
        if ext.host not in hosts:
            hosts[ext.host] = host_workspace_detected(project_root, ext.host)
    statuses = [
        host_extension_status(ext, workspace=hosts.get(ext.host, False))
        for ext in extensions
    ]
    return hosts, statuses
