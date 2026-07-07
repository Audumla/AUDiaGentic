"""Codex config.toml MCP server format handlers.

Codex stores MCP server entries under `[mcp_servers.<name>]` in
`.codex/config.toml`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import tomllib

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.mcp import McpServerEntry

_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _format_key(key: str) -> str:
    if _BARE_KEY_RE.fullmatch(key):
        return key
    if "'" not in key:
        return f"'{key}'"
    return json.dumps(key)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    raise AudiaGenticError(
        code="VAL-PROV-CODEX-MCP-001",
        kind="providers-codex",
        message=f"unsupported TOML value type: {type(value).__name__}",
        details={"type": type(value).__name__},
    )


def _write_table(lines: list[str], path: tuple[str, ...], data: dict[str, Any]) -> None:
    if path:
        lines.append(f"[{'.'.join(_format_key(part) for part in path)}]")
    for key, value in data.items():
        if isinstance(value, dict):
            continue
        lines.append(f"{_format_key(key)} = {_format_scalar(value)}")
    if path:
        lines.append("")
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        _write_table(lines, path + (key,), value)


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise AudiaGenticError(
            code="VAL-PROV-CODEX-MCP-002",
            kind="providers-codex",
            message=f"invalid Codex TOML config: {path}",
            details={"path": str(path)},
        ) from exc
    except OSError as exc:
        raise AudiaGenticError(
            code="VAL-PROV-CODEX-MCP-003",
            kind="providers-codex",
            message=f"unable to read Codex TOML config: {path}",
            details={"path": str(path)},
        ) from exc


def _save_toml(path: Path, data: dict[str, Any]) -> None:
    lines: list[str] = []
    _write_table(lines, (), data)
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def read_codex_toml(path: Path) -> dict[str, McpServerEntry]:
    data = _load_toml(path)
    servers = data.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise AudiaGenticError(
            code="VAL-PROV-CODEX-MCP-004",
            kind="providers-codex",
            message=f"invalid Codex MCP config shape: {path}",
            details={"path": str(path)},
        )
    result: dict[str, McpServerEntry] = {}
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        result[name] = McpServerEntry(
            name=name,
            command=str(server.get("command", "")),
            args=tuple(server.get("args", [])),
            env=dict(server.get("env", {})),
        )
    return result


def write_codex_toml(path: Path, entries: dict[str, McpServerEntry]) -> None:
    existing = _load_toml(path)
    servers = existing.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        raise AudiaGenticError(
            code="VAL-PROV-CODEX-MCP-004",
            kind="providers-codex",
            message=f"invalid Codex MCP config shape: {path}",
            details={"path": str(path)},
        )
    for name, entry in entries.items():
        current = servers.get(name, {})
        if current and not isinstance(current, dict):
            raise AudiaGenticError(
                code="VAL-PROV-CODEX-MCP-005",
                kind="providers-codex",
                message=f"invalid Codex MCP entry shape for {name}: {path}",
                details={"name": name, "path": str(path)},
            )
        updated = dict(current) if isinstance(current, dict) else {}
        updated["command"] = entry.command
        updated["args"] = list(entry.args)
        updated["enabled"] = True
        if entry.env:
            updated["env"] = dict(entry.env)
        else:
            updated.pop("env", None)
        servers[name] = updated
    _save_toml(path, existing)


def remove_codex_toml(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    existing = _load_toml(path)
    servers = existing.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise AudiaGenticError(
            code="VAL-PROV-CODEX-MCP-004",
            kind="providers-codex",
            message=f"invalid Codex MCP config shape: {path}",
            details={"path": str(path)},
        )
    if name not in servers:
        return False
    del servers[name]
    _save_toml(path, existing)
    return True
