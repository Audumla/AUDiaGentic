"""Opencode plugin-array config adapter.

Opencode auto-installs packages listed in the top-level "plugin" array of
opencode.json on startup — there is no separate install command. Entries are
either a bare package name (``"pkg"``) or a ``[package, options]`` pair. These
functions upsert one named entry by package name while preserving all other
entries already present in the array.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _split_entry(entry: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(entry, list) and entry:
        name = entry[0]
        options = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
        return name, options
    return str(entry), {}


def read_opencode_plugin(path: Path, package: str) -> dict[str, Any] | None:
    """Return the options dict for ``package`` if present in the plugin array, else None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    for entry in data.get("plugin", []):
        name, options = _split_entry(entry)
        if name == package:
            return options
    return None


def write_opencode_plugin(path: Path, package: str, options: dict[str, Any]) -> None:
    """Upsert ``package`` (with ``options``) into the plugin array, preserving other entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    plugins = list(existing.get("plugin", []))
    entry: Any = [package, options] if options else package
    for index, item in enumerate(plugins):
        name, _ = _split_entry(item)
        if name == package:
            plugins[index] = entry
            break
    else:
        plugins.append(entry)
    existing["plugin"] = plugins
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def remove_opencode_plugin(path: Path, package: str) -> bool:
    """Remove ``package`` from the plugin array. Returns True if it was present."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    plugins = data.get("plugin", [])
    filtered = [item for item in plugins if _split_entry(item)[0] != package]
    if len(filtered) == len(plugins):
        return False
    data["plugin"] = filtered
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True
