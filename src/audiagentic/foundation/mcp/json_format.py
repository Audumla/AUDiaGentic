"""Shared MCP JSON format helpers.

Standard shape (stdio):
  {"mcpServers": {"name": {"command": ..., "args": [...], "env": {...}}}}

Remote shape:
  {"mcpServers": {"name": {"type": "http", "url": "...", "headers": {...}}}}

Preserves unknown top-level keys on write. Writes OS-agnostic python placeholder
for AUDiaGentic-owned entries; resolves at read time to current sys.executable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.mcp import McpServerEntry

_PYTHON_PLACEHOLDER = "__AUDIAGENTIC_PYTHON__"


def _is_audiagentic_python_entry(args: tuple[str, ...]) -> bool:
    """Return True if this entry uses audiagentic's launcher module."""
    return any("audiagentic.launcher" in a for a in args)


def _resolve_command(command: str) -> str:
    """Resolve python placeholder to current sys.executable on read."""
    if command == _PYTHON_PLACEHOLDER:
        return str(sys.executable)
    return command


def _sanitize_command(command: str, args: tuple[str, ...]) -> str:
    """Replace absolute python path with OS-agnostic placeholder on write."""
    if _is_audiagentic_python_entry(args) and command == str(sys.executable):
        return _PYTHON_PLACEHOLDER
    return command


def read_mcp_json(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    entries: dict[str, McpServerEntry] = {}
    for name, cfg in data.get("mcpServers", {}).items():
        if "url" in cfg:
            entries[name] = McpServerEntry(
                name=name,
                url=cfg["url"],
                headers=dict(cfg.get("headers", {})),
                transport=cfg.get("type"),
            )
        else:
            raw_args = tuple(cfg.get("args", []))
            entries[name] = McpServerEntry(
                name=name,
                command=_resolve_command(cfg.get("command", "")),
                args=raw_args,
                env=dict(cfg.get("env", {})),
            )
    return entries


def write_mcp_json(path: Path, entries: dict[str, McpServerEntry]) -> None:
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    servers: dict[str, Any] = existing.get("mcpServers", {})
    for name, entry in entries.items():
        if entry.is_remote:
            cfg: dict[str, Any] = {
                "type": entry.transport or "http",
                "url": entry.url,
            }
            if entry.headers:
                cfg["headers"] = dict(entry.headers)
        else:
            cfg = {
                "command": _sanitize_command(entry.command, entry.args),
                "args": list(entry.args),
            }
            if entry.env:
                cfg["env"] = dict(entry.env)
        servers[name] = cfg
    existing["mcpServers"] = servers
    atomic_write_json(path, existing, indent=2, sort_keys=False)


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
    atomic_write_json(path, data, indent=2, sort_keys=False)
    return True
