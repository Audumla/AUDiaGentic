"""External MCP server probe observer.

Subscribes to component lifecycle events and caches probe results for any
ExternalMcpServerDeclaration entries that declare a probe command. Results
are stored in the component marker so collect_mcp_servers can read them at
runtime without running subprocesses on every launch.

Import this module to activate the subscription. Importing multiple times
is safe — registration is guarded by a module-level flag.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.registry import get_descriptor
from audiagentic.foundation.event import subscribe_component_lifecycle
from audiagentic.foundation.system.probe import probe_binary

_REGISTERED = False


def _run_and_store_probes(component_id: str, project_root: Path) -> None:
    descriptor = get_descriptor(component_id)
    if descriptor is None or not descriptor.external_mcp_servers:
        return
    results: dict[str, bool] = {}
    for ext in descriptor.external_mcp_servers:
        if not ext.probe and not ext.requires:
            continue
        results[ext.name] = probe_binary(
            ext.name,
            tuple(ext.requires),
            list(ext.probe) if ext.probe else None,
        )
    if not results:
        return
    from audiagentic.foundation.lifecycle.components import _read_marker, _write_marker
    data = _read_marker(component_id, project_root)
    data["external-mcp-probe"] = results
    _write_marker(component_id, project_root, data)


def _on_lifecycle_event(project_root: Path, payload: dict, metadata: dict) -> None:
    _run_and_store_probes(payload["component_id"], project_root)


def register() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    subscribe_component_lifecycle(
        None,
        on_installed=_on_lifecycle_event,
        on_enabled=_on_lifecycle_event,
    )
    _REGISTERED = True


register()
