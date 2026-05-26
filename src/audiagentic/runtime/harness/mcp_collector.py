"""Harness-generic MCP server collection.

Scans all installed/enabled components and returns a dict of McpServerEntry
objects keyed by server name. Format-specific writing and harness-specific
config structure are the responsibility of each harness.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import (
    all_descriptors,
    get_external_probe_results,
    is_enabled,
    is_installed,
)
from audiagentic.foundation.mcp import McpServerEntry


def _python_exe() -> str:
    return sys.executable.replace("\\", "/")


def _src_path() -> str:
    from audiagentic.runtime.harness.paths import find_package_root
    return str(find_package_root(Path(__file__)).parent).replace("\\", "/")


def collect_mcp_servers(project_root: Path | None = None) -> dict[str, McpServerEntry]:
    """Collect MCP server entries from all installed/enabled components.

    External servers whose requirements are missing or probes failed are
    excluded. Returns a dict mapping server name to McpServerEntry.
    """
    if project_root is None:
        project_root = Path.cwd()

    register_all_components()

    python = _python_exe()
    src_dir = _src_path()
    servers: dict[str, McpServerEntry] = {}

    for cid, descriptor in all_descriptors().items():
        active = descriptor.core or (
            is_installed(cid, project_root) and is_enabled(cid, project_root)
        )
        if not active:
            continue

        for decl in descriptor.mcp_servers:
            servers[decl.name] = McpServerEntry(
                name=decl.name,
                command=python,
                args=("-m", decl.module) + tuple(decl.args),
                env={"PYTHONPATH": src_dir},
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
