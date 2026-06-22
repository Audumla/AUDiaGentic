"""Goose config.yaml MCP server format handlers.

Format: YAML with an extensions list; stdio entries map to MCP servers.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.mcp import McpServerEntry


def read_goose_yaml(path: Path) -> dict[str, McpServerEntry]:
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


def write_goose_yaml(path: Path, entries: dict[str, McpServerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError) as exc:
            raise AudiaGenticError(
                code="VAL-PROV-GOOSE-MCP-001",
                kind="providers-goose",
                message=f"invalid goose YAML config: {path}",
                details={"path": str(path)},
            ) from exc
    extensions: list[dict] = list(existing.get("extensions", []))
    by_name = {e.get("name"): i for i, e in enumerate(extensions) if e.get("type") == "stdio"}
    for name, entry in entries.items():
        ext_entry: dict = {
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


def remove_goose_yaml(path: Path, name: str) -> bool:
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
