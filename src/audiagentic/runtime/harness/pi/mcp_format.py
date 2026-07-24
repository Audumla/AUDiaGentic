"""Pi harness MCP config format handler.

Pi uses a superset of the generic mcp-json format for a *full rebuild*: each
server entry carries a ``lifecycle`` field and the file has a top-level
``settings`` block (see ``build_pi_mcp_dict``, used by the install path).

Individual entry management (add/remove a single server without touching the
rest) doesn't need those full-rebuild-only fields — matching OpenCode's
mcp_format.py, this delegates straight to the shared
foundation/mcp/json_format.py implementation rather than carrying a second,
Pi-specific read/write/remove implementation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.json_format import (
    _resolve_command,
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)

_PI_SETTINGS_ENABLED: dict[str, Any] = {
    "toolPrefix": "mcp",
    "idleTimeout": 10,
    "directTools": True,
}
_PI_SETTINGS_DISABLED: dict[str, Any] = {
    "toolPrefix": "mcp",
    "idleTimeout": 10,
    "directTools": False,
}


def pi_mcp_path(project_root: Path | None = None) -> Path:
    if project_root is None:
        project_root = Path.cwd()
    return project_root / ".audiagentic" / "mcp.json"


mcp_config_path = pi_mcp_path


def _entry_to_pi_cfg(entry: McpServerEntry) -> dict[str, Any]:
    # Pi's MCP adapter consumes this file directly, so runtime config must not
    # contain AUDiaGentic-only portability placeholders.
    cfg: dict[str, Any] = {
        "command": _resolve_command(entry.command),
        "args": list(entry.args),
        "lifecycle": "lazy",
    }
    if entry.env:
        cfg["env"] = dict(entry.env)
    return cfg


def build_pi_mcp_dict(
    entries: dict[str, McpServerEntry],
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Build a complete pi mcp.json structure from a full discovered entry set.

    Called by the install path for full rebuilds — not by individual management.
    """
    if not enabled:
        return {"settings": _PI_SETTINGS_DISABLED, "mcpServers": {}}
    return {
        "settings": _PI_SETTINGS_ENABLED,
        "mcpServers": {name: _entry_to_pi_cfg(e) for name, e in entries.items()},
    }


__all__ = [
    "build_pi_mcp_dict",
    "mcp_config_path",
    "pi_mcp_path",
    "read_mcp_json",
    "remove_mcp_json",
    "write_mcp_json",
]
