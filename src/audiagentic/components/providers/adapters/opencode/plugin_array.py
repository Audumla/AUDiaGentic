"""Opencode plugin-array config adapter.

Opencode auto-installs packages listed in the top-level "plugin" array of
opencode.json on startup — there is no separate install command. Entries are
either a bare package name (``"pkg"``) or a ``[package, options]`` pair. This
adapter presents the plugin array as a name-keyed dict for use with the shared
managed-config engine: reader(path) -> {name: options}, writer(path, {name: options}),
remover(path, name).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_json, load_json_file


def _split_entry(entry: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(entry, list) and entry:
        name = entry[0]
        options = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
        return name, options
    return str(entry), {}


def _entry_to_array(name: str, options: dict[str, Any]) -> Any:
    """Convert a name-keyed entry back to the plugin array format."""
    return [name, options] if options else name


def read_opencode_plugins(path: Path) -> dict[str, Any]:
    """Read the full plugin array as a name-keyed dict: {package_name: options}."""
    data = load_json_file(path)
    result: dict[str, Any] = {}
    for entry in data.get("plugin", []):
        name, options = _split_entry(entry)
        result[name] = options
    return result


def write_opencode_plugins(path: Path, plugins: dict[str, Any]) -> None:
    """Upsert one or more plugin entries into the plugin array, preserving other
    entries already present. The ``plugins`` dict maps package_name -> options;
    only listed keys are touched, all others remain unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_json_file(path)
    plugins_list = list(existing.get("plugin", []))

    # Build a set of existing entry names and their indices for fast lookup
    existing_names: dict[str, int] = {}
    for idx, item in enumerate(plugins_list):
        name, _ = _split_entry(item)
        existing_names[name] = idx

    # Upsert / append entries from the plugins dict
    for name, opts in plugins.items():
        if name in existing_names:
            plugins_list[existing_names[name]] = _entry_to_array(name, opts)
        else:
            plugins_list.append(_entry_to_array(name, opts))

    existing["plugin"] = plugins_list
    atomic_write_json(path, existing)


def remove_opencode_plugin(path: Path, package: str) -> bool:
    """Remove ``package`` from the plugin array. Returns True if it was present."""
    data = load_json_file(path)
    if not data:
        return False
    plugins = data.get("plugin", [])
    filtered = [item for item in plugins if _split_entry(item)[0] != package]
    if len(filtered) == len(plugins):
        return False
    data["plugin"] = filtered
    atomic_write_json(path, data)
    return True
