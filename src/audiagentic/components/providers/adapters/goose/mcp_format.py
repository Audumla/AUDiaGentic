"""Goose config.yaml MCP extension format handlers.

Goose stores MCP servers as *extensions*. Per Goose's own configuration
documentation (https://block.github.io/goose — "Add Extension -> Remote
Extension (Streamable HTTP)"), ``extensions`` is a **mapping** keyed by
extension name, and remote servers use ``type: streamable_http`` with ``uri``
and ``headers``::

    extensions:
      some-server:
        type: streamable_http
        name: some-server
        enabled: true
        uri: "https://example.invalid/mcp/"
        headers:
          Authorization: "Bearer ..."

Local servers use ``type: stdio`` with ``cmd``/``args``/``envs`` instead.

This module is a format serializer only: it translates a provider-neutral
:class:`McpServerEntry` to and from Goose's spelling. It knows nothing about
which server is being registered or why — callers supply that.

Reads also tolerate a top-level ``extensions`` *list*, because earlier versions
of this module emitted that shape into real user configs. Writes always produce
the documented mapping form and normalise a legacy list on the way through.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.mcp import McpServerEntry

#: Goose's documented remote extension type. Goose retains ``sse`` only for
#: backward compatibility, so it is read-tolerated but never written.
_REMOTE_TYPE = "streamable_http"
_LEGACY_REMOTE_TYPE = "sse"
_STDIO_TYPE = "stdio"


def _iter_extensions(raw: Any) -> list[tuple[str, dict]]:
    """Yield ``(name, extension)`` pairs from the mapping or legacy list form."""
    if isinstance(raw, dict):
        return [(str(name), ext) for name, ext in raw.items() if isinstance(ext, dict)]
    if isinstance(raw, list):
        return [
            (str(ext.get("name", "")), ext)
            for ext in raw
            if isinstance(ext, dict) and ext.get("name")
        ]
    return []


def read_goose_yaml(path: Path) -> dict[str, McpServerEntry]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}

    result: dict[str, McpServerEntry] = {}
    for name, ext in _iter_extensions(data.get("extensions")):
        if not name:
            continue
        ext_type = ext.get("type")
        if ext_type in (_REMOTE_TYPE, _LEGACY_REMOTE_TYPE):
            uri = ext.get("uri", "")
            if not uri:
                continue
            result[name] = McpServerEntry(
                name=name,
                url=uri,
                headers=dict(ext.get("headers") or {}),
                transport=str(ext_type),
            )
        elif ext_type == _STDIO_TYPE:
            result[name] = McpServerEntry(
                name=name,
                command=ext.get("cmd", ""),
                args=tuple(ext.get("args") or ()),
                env=dict(ext.get("envs") or {}),
            )
    return result


def _as_extension(entry: McpServerEntry) -> dict[str, Any]:
    """Render one provider-neutral entry in Goose's extension shape."""
    if entry.is_remote:
        return {
            "name": entry.name,
            "type": _REMOTE_TYPE,
            "enabled": True,
            "uri": entry.url,
            "headers": dict(entry.headers or {}),
        }
    return {
        "name": entry.name,
        "type": _STDIO_TYPE,
        "enabled": True,
        "cmd": entry.command,
        "args": list(entry.args),
        "envs": dict(entry.env or {}),
    }


def write_goose_yaml(path: Path, entries: dict[str, McpServerEntry]) -> None:
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

    # Preserve every unrelated extension and every unrelated top-level setting.
    extensions = dict(_iter_extensions(existing.get("extensions")))
    for name, entry in entries.items():
        extensions[name] = _as_extension(entry)

    existing["extensions"] = extensions
    atomic_write_text(path, yaml.dump(existing, default_flow_style=False, sort_keys=False))


def remove_goose_yaml(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return False

    extensions = dict(_iter_extensions(data.get("extensions")))
    if name not in extensions:
        return False
    del extensions[name]
    data["extensions"] = extensions
    atomic_write_text(path, yaml.dump(data, default_flow_style=False, sort_keys=False))
    return True
