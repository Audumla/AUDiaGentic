"""TOML MCP config reader/writer for OpenHands [mcp_servers] format."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment,misc]

from audiagentic.foundation.mcp import McpServerEntry


def read_mcp_toml(path: Path) -> dict[str, McpServerEntry]:
    """Read MCP server entries from a TOML file's [mcp_servers] section."""
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    entries: dict[str, McpServerEntry] = {}
    for name, cfg in data.get("mcp_servers", {}).items():
        if not isinstance(cfg, dict):
            continue
        if "url" in cfg:
            entries[name] = McpServerEntry(
                name=name,
                url=cfg["url"],
                headers=dict(cfg.get("headers", {})),
                transport=cfg.get("type"),
            )
        else:
            entries[name] = McpServerEntry(
                name=name,
                command=cfg.get("command", ""),
                args=tuple(cfg.get("args", [])),
                env=dict(cfg.get("env", {})),
            )
    return entries


def write_mcp_toml(path: Path, entries: dict[str, McpServerEntry]) -> None:
    """Write MCP server entries to a TOML file's [mcp_servers] section."""
    if tomli_w is None:
        raise RuntimeError("tomli_w required; pip install tomli-w")
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            pass

    servers: dict[str, Any] = existing.get("mcp_servers", {})
    for name, entry in entries.items():
        if entry.is_remote:
            cfg: dict[str, Any] = {"type": entry.transport or "http", "url": entry.url}
            if entry.headers:
                cfg["headers"] = dict(entry.headers)
        else:
            cfg = {"command": entry.command, "args": list(entry.args)}
            if entry.env:
                cfg["env"] = dict(entry.env)
        servers[name] = cfg
    existing["mcp_servers"] = servers
    path.write_text(tomli_w.dumps(existing), encoding="utf-8")


def remove_mcp_toml(path: Path, name: str) -> bool:
    """Remove an MCP server entry by name from a TOML file."""
    if tomli_w is None:
        raise RuntimeError("tomli_w required; pip install tomli-w")
    if not path.exists():
        return False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return False
    servers = data.get("mcp_servers", {})
    if name not in servers:
        return False
    del servers[name]
    data["mcp_servers"] = servers
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
    return True
