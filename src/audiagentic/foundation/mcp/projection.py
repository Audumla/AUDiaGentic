"""Project component declarations into deterministic MCP server entries.

This module owns selection only.  Provider and harness adapters own the
materialization format used by a durable config or one process launch.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.foundation.components.registry import (
    all_descriptors,
    get_external_probe_results,
    is_enabled,
    is_installed,
)
from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.component_builder import (
    entry_from_external_declaration,
    entry_from_mcp_declaration,
)


def _component_contributes(
    component_id: str,
    *,
    core: bool,
    project_root: Path,
    require_enabled: bool,
) -> bool:
    if core:
        return True
    if not is_installed(component_id, project_root):
        return False
    return not require_enabled or is_enabled(component_id, project_root)


def _add_entry(servers: dict[str, McpServerEntry], entry: McpServerEntry) -> None:
    incumbent = servers.get(entry.name)
    if incumbent is not None and incumbent != entry:
        raise make_error(
            prefix="VAL",
            component="MCPPRJ",
            number=1,
            kind="mcp-projection",
            message="conflicting MCP server declarations use the same name",
            details={"server-name": entry.name},
        )
    servers[entry.name] = entry


def collect_component_mcp_entries(
    project_root: Path | None = None,
    *,
    propagation_target: str,
    require_enabled: bool,
) -> dict[str, McpServerEntry]:
    """Collect entries matching one caller-owned propagation policy.

    Foundation performs descriptor selection and entry construction only. The
    caller owns the domain meaning of ``propagation_target`` and whether an
    installed component must also be enabled.
    """
    root = (project_root or Path.cwd()).resolve()
    servers: dict[str, McpServerEntry] = {}

    for component_id, descriptor in sorted(all_descriptors().items()):
        if not _component_contributes(
            component_id,
            core=descriptor.core,
            project_root=root,
            require_enabled=require_enabled,
        ):
            continue

        for declaration in descriptor.mcp_servers:
            if propagation_target in declaration.propagate:
                _add_entry(servers, entry_from_mcp_declaration(declaration, root))

        probe_cache = get_external_probe_results(component_id, root)
        for declaration in descriptor.external_mcp_servers:
            if propagation_target not in declaration.propagate:
                continue
            if any(shutil.which(requirement) is None for requirement in declaration.requires):
                continue
            if declaration.probe and probe_cache.get(declaration.name) is False:
                continue
            _add_entry(servers, entry_from_external_declaration(declaration))

    return servers


__all__ = ["collect_component_mcp_entries"]
