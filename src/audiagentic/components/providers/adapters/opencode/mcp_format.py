"""Opencode-specific MCP config adapter.

Opencode uses .opencode/opencode.json with format:
  {"mcp": {"name": {"type": "local", "command": [...], "environment": {...}}}}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.mcp import McpServerEntry

_opencode_mcp_error = make_error_factory("CFG", "OCMCP", "providers-opencode")


def _load_opencode_json(path: Path) -> dict[str, Any]:
    """Missing opencode.json returns {}; malformed content raises instead of
    being silently treated the same as absent (RV713) — the next managed
    write would otherwise overwrite and discard whatever was on disk."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _opencode_mcp_error(1, f"Invalid opencode.json: {path}", path=str(path)) from exc


def read_opencode_mcp(path: Path) -> dict[str, McpServerEntry]:
    data = _load_opencode_json(path)
    result: dict[str, McpServerEntry] = {}
    for name, cfg in data.get("mcp", {}).items():
        if cfg.get("type") == "remote":
            result[name] = McpServerEntry(
                name=name,
                url=cfg.get("url"),
                headers=dict(cfg.get("headers", {})),
                transport="http",
            )
            continue
        result[name] = McpServerEntry(
            name=name,
            command=cfg.get("command", [""])[0] if isinstance(cfg.get("command"), list) else cfg.get("command", ""),
            args=(
                tuple(cfg.get("command", [])[1:])
                if isinstance(cfg.get("command"), list) and len(cfg.get("command", [])) > 1
                else ()
            ),
            env=dict(cfg.get("environment", {})),
        )
    return result


def write_opencode_mcp(path: Path, entries: dict[str, McpServerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_opencode_json(path)
    servers: dict[str, Any] = existing.get("mcp", {})
    for name, entry in entries.items():
        if entry.is_remote:
            cfg = {"type": "remote", "url": entry.url}
            if entry.headers:
                cfg["headers"] = dict(entry.headers)
        else:
            cmd = [entry.command] + list(entry.args)
            cfg = {"type": "local", "command": cmd}
            if entry.env:
                cfg["environment"] = dict(entry.env)
        servers[name] = cfg
    existing["mcp"] = servers
    atomic_write_json(path, existing)


def remove_opencode_mcp(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    data = _load_opencode_json(path)
    servers = data.get("mcp", {})
    if name not in servers:
        return False
    del servers[name]
    data["mcp"] = servers
    atomic_write_json(path, data)
    return True
