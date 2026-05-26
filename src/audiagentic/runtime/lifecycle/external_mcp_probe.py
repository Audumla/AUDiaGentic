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
from audiagentic.foundation.event import get_bus
from audiagentic.foundation.system.probe import probe_binary
from audiagentic.runtime.lifecycle.observers import (
    COMPONENT_ENABLED,
    COMPONENT_INSTALLED,
)

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
    from audiagentic.runtime.lifecycle.components import _read_marker, _write_marker
    data = _read_marker(component_id, project_root)
    data["external-mcp-probe"] = results
    _write_marker(component_id, project_root, data)


def _on_lifecycle_event(event_type: str, payload: dict, metadata: dict) -> None:
    component_id = payload.get("component_id")
    project_root = payload.get("project_root")
    if not component_id or not isinstance(project_root, Path):
        return
    _run_and_store_probes(component_id, project_root)


def register() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    bus = get_bus()
    bus.subscribe(COMPONENT_INSTALLED, _on_lifecycle_event)
    bus.subscribe(COMPONENT_ENABLED, _on_lifecycle_event)
    _REGISTERED = True


register()
