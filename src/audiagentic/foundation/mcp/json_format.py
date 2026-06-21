"""Shared MCP JSON format helpers.

Standard shape:
  {"mcpServers": {"name": {"command": ..., "args": [...], "env": {...}}}}

Preserves unknown top-level keys on write.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.mcp import McpServerEntry


def read_mcp_json(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        name: McpServerEntry(
            name=name,
            command=cfg.get("command", ""),
            args=tuple(cfg.get("args", [])),
            env=dict(cfg.get("env", {})),
        )
        for name, cfg in data.get("mcpServers", {}).items()
    }


def write_mcp_json(path: Path, entries: dict[str, McpServerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    servers: dict[str, Any] = existing.get("mcpServers", {})
    for name, entry in entries.items():
        cfg: dict[str, Any] = {"command": entry.command, "args": list(entry.args)}
        if entry.env:
            cfg["env"] = dict(entry.env)
        servers[name] = cfg
    existing["mcpServers"] = servers
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def remove_mcp_json(path: Path, name: str) -> bool:
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
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True
