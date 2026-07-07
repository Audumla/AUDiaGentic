"""Harness-generic MCP server collection.

Scans all installed/enabled components and returns a dict of McpServerEntry
objects keyed by server name. Format-specific writing and harness-specific
config structure are the responsibility of each harness.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components  # noqa: F401
from audiagentic.foundation.components.registry import (
    all_descriptors,
    get_external_probe_results,
    is_enabled,
    is_installed,
)
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.component_builder import (
    entry_from_external_declaration,
    entry_from_mcp_declaration,
)


def collect_mcp_servers(project_root: Path | None = None) -> dict[str, McpServerEntry]:
    """Collect MCP server entries from all installed/enabled components.

    External servers whose requirements are missing or probes failed are
    excluded. Returns a dict mapping server name to McpServerEntry.
    """
    if project_root is None:
        project_root = Path.cwd()

    servers: dict[str, McpServerEntry] = {}

    for cid, descriptor in all_descriptors().items():
        active = descriptor.core or (
            is_installed(cid, project_root) and is_enabled(cid, project_root)
        )
        if not active:
            continue

        for decl in descriptor.mcp_servers:
            if "audiagentic" not in decl.propagate:
                continue
            servers[decl.name] = entry_from_mcp_declaration(decl)

        probe_cache = get_external_probe_results(cid, project_root)
        for ext in descriptor.external_mcp_servers:
            if "audiagentic" not in ext.propagate:
                continue
            if any(shutil.which(r) is None for r in ext.requires):
                continue
            if ext.probe and probe_cache.get(ext.name) is False:
                continue
            servers[ext.name] = entry_from_external_declaration(ext)

    return servers
