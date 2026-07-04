"""Continue config.json MCP server format handlers.

Format: {"mcpServers": [{"name": ..., "command": ..., "args": [...]}]}
Also accepts the map form used by some Continue configs:
{"mcpServers": {"name": {"command": ..., "args": [...]}}}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.mcp import McpServerEntry


def _server_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items = []
        for name, server in value.items():
            if isinstance(server, dict):
                items.append({"name": name, **server})
        return items
    if isinstance(value, list):
        return [server for server in value if isinstance(server, dict)]
    return []


def read_continue_json(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    result = {}
    for server in _server_items(data.get("mcpServers", [])):
        name = server.get("name", "")
        if not name:
            continue
        if "url" in server:
            result[name] = McpServerEntry(
                name=name,
                url=server["url"],
                headers=dict(server.get("headers", {})),
                transport=server.get("type"),
            )
        else:
            result[name] = McpServerEntry(
                name=name,
                command=server.get("command", ""),
                args=tuple(server.get("args", [])),
                env=dict(server.get("env", {})),
            )
    return result


def write_continue_json(path: Path, entries: dict[str, McpServerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    servers = _server_items(existing.get("mcpServers", []))
    by_name = {s.get("name"): i for i, s in enumerate(servers)}
    for name, entry in entries.items():
        if entry.is_remote:
            server_entry = {
                "name": entry.name,
                "type": entry.transport or "http",
                "url": entry.url,
            }
            if entry.headers:
                server_entry["headers"] = dict(entry.headers)
        else:
            server_entry = {
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


def remove_continue_json(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    servers = _server_items(data.get("mcpServers", []))
    new_servers = [s for s in servers if s.get("name") != name]
    if len(new_servers) == len(servers):
        return False
    data["mcpServers"] = new_servers
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True
