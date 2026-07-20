"""TOML MCP config reader/writer for OpenHands [mcp_servers] format."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import tomllib

from audiagentic.foundation.contracts.errors import make_error, make_error_factory
from audiagentic.foundation.io import atomic_write_text

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment,misc]

from audiagentic.foundation.mcp import McpServerEntry

_openhands_toml_error = make_error_factory("CFG", "OHTOML", "providers-openhands")


def _load_mcp_toml(path: Path) -> dict[str, Any]:
    """Missing config.toml returns {}; malformed content raises instead of
    being silently treated the same as absent (RV713) — the next managed
    write would otherwise overwrite and discard whatever was on disk."""
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise _openhands_toml_error(1, f"Invalid OpenHands config.toml: {path}", path=str(path)) from exc


def read_mcp_toml(path: Path) -> dict[str, McpServerEntry]:
    """Read MCP server entries from a TOML file's [mcp_servers] section."""
    data = _load_mcp_toml(path)
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
        raise make_error(
            prefix="RES",
            component="OHAND",
            number=1,
            kind="providers",
            message="tomli_w required; pip install tomli-w",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_mcp_toml(path)
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
    atomic_write_text(path, tomli_w.dumps(existing))


def remove_mcp_toml(path: Path, name: str) -> bool:
    """Remove an MCP server entry by name from a TOML file."""
    if tomli_w is None:
        raise make_error(
            prefix="RES",
            component="OHAND",
            number=1,
            kind="providers",
            message="tomli_w required; pip install tomli-w",
        )
    if not path.exists():
        return False
    data = _load_mcp_toml(path)
    servers = data.get("mcp_servers", {})
    if name not in servers:
        return False
    del servers[name]
    data["mcp_servers"] = servers
    atomic_write_text(path, tomli_w.dumps(data))
    return True
