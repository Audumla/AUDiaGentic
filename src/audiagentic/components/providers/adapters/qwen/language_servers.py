"""Qwen Code .lsp.json language server format handlers.

Qwen Code reads language servers from a top-level `.lsp.json` in the project
root, keyed by language id. The whole file IS the language-server map. Each
entry uses a string `command` plus a separate `args` array:

    { "python": { "command": "pyright-langserver", "args": ["--stdio"],
                  "extensionToLanguage": {".py": "python"} } }

The full document is preserved on write — only managed language keys are
touched, leaving any user-added languages intact.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp.language_servers import LanguageServerEntry
from audiagentic.foundation.io import _ensure_dict


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _ensure_dict(data)


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_language_servers_qwen(path: Path) -> dict[str, LanguageServerEntry]:
    data = _load_json(path)
    result: dict[str, LanguageServerEntry] = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        command_str = cfg.get("command", "")
        command = [command_str] if command_str else []
        command.extend(cfg.get("args", []))
        extensions = list(cfg.get("extensionToLanguage", {}).keys())
        result[name] = LanguageServerEntry(
            language=name,
            command=command,
            file_extensions=extensions,
            settings=dict(cfg.get("settings", {})),
        )
    return result


def write_language_servers_qwen(path: Path, entries: dict[str, LanguageServerEntry]) -> None:
    data = _load_json(path)
    for name, entry in entries.items():
        if not entry.command:
            continue  # qwen requires a command string; skip empty
        node: dict[str, Any] = {
            "command": entry.command[0],
            "args": list(entry.command[1:]),
            "extensionToLanguage": {ext: name for ext in entry.file_extensions},
        }
        if entry.settings:
            node["settings"] = dict(entry.settings)
        data[name] = node
    _save_json(path, data)


def remove_language_servers_qwen(path: Path, language: str) -> bool:
    data = _load_json(path)
    if language not in data:
        return False
    del data[language]
    if data:
        _save_json(path, data)
    else:
        # The whole file is the language-server container (keyed at the root),
        # so remove it entirely rather than leaving an empty "{}".
        path.unlink(missing_ok=True)
    return True
