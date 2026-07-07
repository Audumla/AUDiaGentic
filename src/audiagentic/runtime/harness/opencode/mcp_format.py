"""Opencode harness MCP config format handler.

Opencode uses the standard mcp-json format — {"mcpServers": {...}}.
Config lives at the project root as .mcp.json (watched live by opencode).
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.json_format import (
    _sanitize_command,
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)


def opencode_mcp_path(project_root: Path | None = None) -> Path:
    if project_root is None:
        import os
        project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", "."))
    return (project_root / ".mcp.json").resolve()


def build_opencode_mcp_dict(
    entries: dict[str, McpServerEntry],
    *,
    enabled: bool = True,
) -> dict:
    if not enabled:
        return {"mcpServers": {}}
    return {
        "mcpServers": {
            name: {
                "type": "stdio",
                "command": _sanitize_command(e.command, e.args),
                "args": list(e.args),
                **({"env": dict(e.env)} if e.env else {}),
            }
            for name, e in entries.items()
        }
    }


__all__ = [
    "build_opencode_mcp_dict",
    "opencode_mcp_path",
    "read_mcp_json",
    "remove_mcp_json",
    "write_mcp_json",
]
