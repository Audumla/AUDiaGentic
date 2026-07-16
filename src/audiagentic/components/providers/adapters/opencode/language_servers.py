"""OpenCode opencode.json language server format handlers.

OpenCode stores language servers under the top-level `lsp` object in
`.opencode/opencode.json` (the same file as its MCP config). Each entry:

    "lsp": { "<name>": { "command": [...], "extensions": [...],
                          "initialization": {...} } }

The full document is preserved on write — only the managed `lsp.<name>`
entries are touched, leaving `mcp` and other keys intact.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.language_server_projection import (
    LanguageServerEntry,
)
from audiagentic.foundation.io import atomic_write_json, load_json_file

# opencode keys its `lsp` object by opencode's own built-in server name, which is
# not always our language id. coding-lsp stays language-keyed and generic; the
# adapter maps to/from opencode's keys here. Languages absent from this map use
# their id unchanged (e.g. typescript, rust already match opencode's keys).
_LANGUAGE_TO_OPENCODE_KEY = {
    "python": "pyright",
    "cpp": "clangd",
    "markdown": "marksman",
    "python-ruff": "ruff",
    "rust": "rust",
    "typescript": "typescript",
    "yaml": "yaml-ls",
}
_OPENCODE_KEY_TO_LANGUAGE = {v: k for k, v in _LANGUAGE_TO_OPENCODE_KEY.items()}

_LANGUAGE_ALIASES = {
    "python": {"python", "pyright"},
    "cpp": {"cpp", "clangd"},
    "markdown": {"markdown", "marksman"},
    "python-ruff": {"python-ruff", "ruff"},
    "rust": {"rust", "rust-analyzer"},
    "typescript": {"typescript", "typescript-language-server"},
    "yaml": {"yaml", "yaml-ls"},
}


def _to_opencode_key(language: str) -> str:
    return _LANGUAGE_TO_OPENCODE_KEY.get(language, language)


def _to_language(opencode_key: str) -> str:
    return _OPENCODE_KEY_TO_LANGUAGE.get(opencode_key, opencode_key)


def read_language_servers_opencode(path: Path) -> dict[str, LanguageServerEntry]:
    data = load_json_file(path)
    lsp = data.get("lsp", {})
    if not isinstance(lsp, dict):
        return {}
    result: dict[str, LanguageServerEntry] = {}
    for name, cfg in lsp.items():
        if not isinstance(cfg, dict):
            continue
        language = _to_language(name)
        result[language] = LanguageServerEntry(
            language=language,
            command=list(cfg.get("command", [])),
            file_extensions=list(cfg.get("extensions", [])),
            settings=dict(cfg.get("initialization", {})),
        )
    return result


def write_language_servers_opencode(path: Path, entries: dict[str, LanguageServerEntry]) -> None:
    data = load_json_file(path)
    lsp = data.get("lsp")
    if not isinstance(lsp, dict):
        lsp = {}
        data["lsp"] = lsp
    for name, entry in entries.items():
        for alias in _LANGUAGE_ALIASES.get(name, {name}):
            lsp.pop(alias, None)
        node: dict[str, Any] = {
            "command": list(entry.command),
            "extensions": list(entry.file_extensions),
        }
        if entry.settings:
            node["initialization"] = dict(entry.settings)
        lsp[_to_opencode_key(name)] = node
    atomic_write_json(path, data)


def remove_language_servers_opencode(path: Path, language: str) -> bool:
    data = load_json_file(path)
    lsp = data.get("lsp", {})
    if not isinstance(lsp, dict):
        return False
    removed = False
    for alias in _LANGUAGE_ALIASES.get(language, {language, _to_opencode_key(language)}):
        if alias in lsp:
            del lsp[alias]
            removed = True
    if not removed:
        return False
    # Drop the container entirely when the last managed server is gone, rather
    # than leaving an empty "lsp": {}.
    if not lsp:
        data.pop("lsp", None)
    atomic_write_json(path, data)
    return True
