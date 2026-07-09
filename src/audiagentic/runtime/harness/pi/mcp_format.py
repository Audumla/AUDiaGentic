"""Pi harness MCP config format handler.

Pi uses a superset of the generic mcp-json format — each server entry carries
a ``lifecycle`` field and the file has a top-level ``settings`` block.

Two operations are intentionally distinct:

* ``write_pi_mcp_json`` / ``read_pi_mcp_json`` / ``remove_pi_mcp_json``
  — standard McpConfigSpec callables for individual entry management.

* ``build_pi_mcp_dict`` — full rebuild from a complete discovered entry set;
  called by the install path, not by individual add/remove management.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.json_format import (
    _resolve_command,
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


def read_pi_mcp_json(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        name: McpServerEntry(
            name=name,
            command=_resolve_command(cfg.get("command", "")),
            args=tuple(cfg.get("args", [])),
            env=dict(cfg.get("env", {})),
        )
        for name, cfg in data.get("mcpServers", {}).items()
    }


def write_pi_mcp_json(path: Path, entries: dict[str, McpServerEntry]) -> None:
    """Merge entries into the existing pi mcp.json, preserving unknown servers."""
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    servers: dict[str, Any] = existing.get("mcpServers", {})
    for name, entry in entries.items():
        servers[name] = _entry_to_pi_cfg(entry)
    existing.setdefault("settings", _PI_SETTINGS_ENABLED)
    existing["mcpServers"] = servers
    atomic_write_json(path, existing, indent=2, sort_keys=False)


def remove_pi_mcp_json(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    servers = data.get("mcpServers", {})
    if name not in servers:
        return False
    del servers[name]
    data["mcpServers"] = servers
    atomic_write_json(path, data, indent=2, sort_keys=False)
    return True


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
