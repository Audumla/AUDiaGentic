"""OpenCode opencode.json language server format handlers.

OpenCode stores language servers under the top-level `lsp` object in
`.opencode/opencode.json` (the same file as its MCP config). Each entry:

    "lsp": { "<name>": { "command": [...], "extensions": [...],
                          "initialization": {...} } }

The full document is preserved on write — only the managed `lsp.<name>`
entries are touched, leaving `mcp` and other keys intact.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...descriptors.base import LanguageServerEntry


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_language_servers_opencode(path: Path) -> dict[str, LanguageServerEntry]:
    data = _load_json(path)
    lsp = data.get("lsp", {})
    if not isinstance(lsp, dict):
        return {}
    result: dict[str, LanguageServerEntry] = {}
    for name, cfg in lsp.items():
        if not isinstance(cfg, dict):
            continue
        result[name] = LanguageServerEntry(
            language=name,
            command=list(cfg.get("command", [])),
            file_extensions=list(cfg.get("extensions", [])),
            settings=dict(cfg.get("initialization", {})),
        )
    return result


def write_language_servers_opencode(path: Path, entries: dict[str, LanguageServerEntry]) -> None:
    data = _load_json(path)
    lsp = data.get("lsp")
    if not isinstance(lsp, dict):
        lsp = {}
        data["lsp"] = lsp
    for name, entry in entries.items():
        node: dict[str, Any] = {
            "command": list(entry.command),
            "extensions": list(entry.file_extensions),
        }
        if entry.settings:
            node["initialization"] = dict(entry.settings)
        lsp[name] = node
    _save_json(path, data)


def remove_language_servers_opencode(path: Path, language: str) -> bool:
    data = _load_json(path)
    lsp = data.get("lsp", {})
    if not isinstance(lsp, dict) or language not in lsp:
        return False
    del lsp[language]
    _save_json(path, data)
    return True
