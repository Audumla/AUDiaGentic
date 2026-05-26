"""Opencode-specific MCP config adapter.

Opencode uses .opencode/opencode.json with format:
  {"mcp": {"name": {"type": "local", "command": [...], "environment": {...}}}}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.mcp import McpServerEntry


def read_opencode_mcp(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        name: McpServerEntry(
            name=name,
            command=cfg.get("command", [""])[0] if isinstance(cfg.get("command"), list) else cfg.get("command", ""),
            args=(
                tuple(cfg.get("command", [])[1:])
                if isinstance(cfg.get("command"), list) and len(cfg.get("command", [])) > 1
                else ()
            ),
            env=dict(cfg.get("environment", {})),
        )
        for name, cfg in data.get("mcp", {}).items()
        if cfg.get("type") != "remote"
    }


def write_opencode_mcp(path: Path, entries: dict[str, McpServerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    servers: dict[str, Any] = existing.get("mcp", {})
    for name, entry in entries.items():
        cmd = [entry.command] + list(entry.args)
        cfg: dict[str, Any] = {"type": "local", "command": cmd}
        if entry.env:
            cfg["environment"] = dict(entry.env)
        servers[name] = cfg
    existing["mcp"] = servers
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def remove_opencode_mcp(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    servers = data.get("mcp", {})
    if name not in servers:
        return False
    del servers[name]
    data["mcp"] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True
