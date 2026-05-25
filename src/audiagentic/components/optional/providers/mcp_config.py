"""MCP server config read/write helpers for provider adapters.

Handles three on-disk formats used across providers:
  mcp-json    — {"mcpServers": {"name": {"command": ..., "args": [...]}}}
  goose-yaml  — extensions list with type=stdio entries
  continue-json — {"mcpServers": [{"name": ..., "command": ..., "args": [...]}]}
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class McpServerEntry:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


def _python_exe() -> str:
    return sys.executable.replace("\\", "/")


def _src_path() -> str:
    # parents[4] = src/ directory (parent of the audiagentic package)
    return str(Path(__file__).resolve().parents[4]).replace("\\", "/")


# --- mcp-json format ---

def _read_mcp_json(path: Path) -> dict[str, McpServerEntry]:
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


def _write_mcp_json(path: Path, entries: dict[str, McpServerEntry]) -> None:
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


def _remove_mcp_json(path: Path, name: str) -> bool:
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


# --- goose-yaml format ---

def _read_goose_yaml(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    result = {}
    for ext in data.get("extensions", []):
        if ext.get("type") != "stdio":
            continue
        name = ext.get("name", "")
        if not name:
            continue
        result[name] = McpServerEntry(
            name=name,
            command=ext.get("cmd", ""),
            args=tuple(ext.get("args", [])),
        )
    return result


def _write_goose_yaml(path: Path, entries: dict[str, McpServerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError) as exc:
            raise ValueError(f"invalid goose YAML config: {path}") from exc
    extensions: list[dict[str, Any]] = list(existing.get("extensions", []))
    by_name = {e.get("name"): i for i, e in enumerate(extensions) if e.get("type") == "stdio"}
    for name, entry in entries.items():
        ext_entry: dict[str, Any] = {
            "name": entry.name,
            "type": "stdio",
            "cmd": entry.command,
            "args": list(entry.args),
            "enabled": True,
        }
        if name in by_name:
            extensions[by_name[name]] = ext_entry
        else:
            extensions.append(ext_entry)
    existing["extensions"] = extensions
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False), encoding="utf-8")


def _remove_goose_yaml(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return False
    extensions = data.get("extensions", [])
    new_extensions = [e for e in extensions if e.get("name") != name]
    if len(new_extensions) == len(extensions):
        return False
    data["extensions"] = new_extensions
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return True


# --- continue-json format ---

def _read_continue_json(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    result = {}
    for server in data.get("mcpServers", []):
        name = server.get("name", "")
        if not name:
            continue
        result[name] = McpServerEntry(
            name=name,
            command=server.get("command", ""),
            args=tuple(server.get("args", [])),
            env=dict(server.get("env", {})),
        )
    return result


def _write_continue_json(path: Path, entries: dict[str, McpServerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    servers: list[dict[str, Any]] = list(existing.get("mcpServers", []))
    by_name = {s.get("name"): i for i, s in enumerate(servers)}
    for name, entry in entries.items():
        server_entry: dict[str, Any] = {
            "name": entry.name,
            "command": entry.command,
            "args": list(entry.args),
        }
        if entry.env:
            server_entry["env"] = dict(entry.env)
        if name in by_name:
            servers[by_name[name]] = server_entry
        else:
            servers.append(server_entry)
    existing["mcpServers"] = servers
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _remove_continue_json(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    servers = data.get("mcpServers", [])
    new_servers = [s for s in servers if s.get("name") != name]
    if len(new_servers) == len(servers):
        return False
    data["mcpServers"] = new_servers
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


# --- dispatch tables ---

_READERS = {
    "mcp-json": _read_mcp_json,
    "goose-yaml": _read_goose_yaml,
    "continue-json": _read_continue_json,
}

_WRITERS = {
    "mcp-json": _write_mcp_json,
    "goose-yaml": _write_goose_yaml,
    "continue-json": _write_continue_json,
}

_REMOVERS = {
    "mcp-json": _remove_mcp_json,
    "goose-yaml": _remove_goose_yaml,
    "continue-json": _remove_continue_json,
}


def read_mcp_servers(config_path: Path, fmt: str) -> dict[str, McpServerEntry]:
    handler = _READERS.get(fmt)
    if handler is None:
        raise ValueError(f"unsupported MCP config format: {fmt!r}")
    return handler(config_path)


def write_mcp_servers(config_path: Path, entries: dict[str, McpServerEntry], fmt: str) -> None:
    handler = _WRITERS.get(fmt)
    if handler is None:
        raise ValueError(f"unsupported MCP config format: {fmt!r}")
    handler(config_path, entries)


def remove_mcp_server(config_path: Path, name: str, fmt: str) -> bool:
    handler = _REMOVERS.get(fmt)
    if handler is None:
        raise ValueError(f"unsupported MCP config format: {fmt!r}")
    return handler(config_path, name)


def build_mcp_entry(server_decl: Any) -> McpServerEntry:
    """Convert McpServerDeclaration or ExternalMcpServerDeclaration to McpServerEntry."""
    from audiagentic.foundation.components.base import (
        ExternalMcpServerDeclaration,
        McpServerDeclaration,
    )
    if isinstance(server_decl, McpServerDeclaration):
        return McpServerEntry(
            name=server_decl.name,
            command=_python_exe(),
            args=("-m", server_decl.module) + tuple(server_decl.args),
            env={"PYTHONPATH": _src_path()},
        )
    if isinstance(server_decl, ExternalMcpServerDeclaration):
        return McpServerEntry(
            name=server_decl.name,
            command=server_decl.command,
            args=tuple(server_decl.args),
            env=dict(server_decl.env),
        )
    raise TypeError(f"unsupported server declaration type: {type(server_decl)}")
