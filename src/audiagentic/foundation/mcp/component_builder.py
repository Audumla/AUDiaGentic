"""Entry construction helpers for component MCP declarations.

Shared by the harness collector (audiagentic-propagated) and the provider
projector (providers-propagated) — both build McpServerEntry values from the
same declaration types, differing only in which propagate target they filter
on and whether they gate on host binary availability.
"""
from __future__ import annotations

from audiagentic.foundation.components.base import (
    ExternalMcpServerDeclaration,
    McpServerDeclaration,
)
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.launch import component_mcp_launch


def entry_from_mcp_declaration(decl: McpServerDeclaration) -> McpServerEntry:
    """Build a McpServerEntry for a Python-module-backed MCP server declaration."""
    command, subcommand, args = component_mcp_launch(decl.module, extra_args=tuple(decl.args))
    return McpServerEntry(
        name=decl.name,
        command=command,
        args=(subcommand, *args),
        env={},
    )


def entry_from_external_declaration(ext: ExternalMcpServerDeclaration) -> McpServerEntry:
    """Build a McpServerEntry for an externally-commanded MCP server declaration."""
    return McpServerEntry(
        name=ext.name,
        command=ext.command,
        args=tuple(ext.args),
        env=dict(ext.env) if ext.env else {},
    )
