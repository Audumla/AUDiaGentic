"""Harness-generic MCP server collection.

Scans all installed/enabled components and returns a dict of McpServerEntry
objects keyed by server name. Format-specific writing and harness-specific
config structure are the responsibility of each harness.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import (
    all_descriptors,
    get_external_probe_results,
    is_enabled,
    is_installed,
)
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.launch import component_mcp_launch


def collect_mcp_servers(project_root: Path | None = None) -> dict[str, McpServerEntry]:
    """Collect MCP server entries from all installed/enabled components.

    External servers whose requirements are missing or probes failed are
    excluded. Returns a dict mapping server name to McpServerEntry.
    """
    if project_root is None:
        project_root = Path.cwd()

    register_all_components()

    servers: dict[str, McpServerEntry] = {}

    for cid, descriptor in all_descriptors().items():
        active = descriptor.core or (
            is_installed(cid, project_root) and is_enabled(cid, project_root)
        )
        if not active:
            continue

        for decl in descriptor.mcp_servers:
            command, subcommand, args = component_mcp_launch(
                decl.module,
                extra_args=tuple(decl.args),
            )
            servers[decl.name] = McpServerEntry(
                name=decl.name,
                command=command,
                args=(subcommand, *args),
                env={},
            )

        probe_cache = get_external_probe_results(cid, project_root)
        for ext in descriptor.external_mcp_servers:
            if any(shutil.which(r) is None for r in ext.requires):
                continue
            if ext.probe and probe_cache.get(ext.name) is False:
                continue
            servers[ext.name] = McpServerEntry(
                name=ext.name,
                command=ext.command,
                args=tuple(ext.args),
                env=dict(ext.env),
            )

    return servers
