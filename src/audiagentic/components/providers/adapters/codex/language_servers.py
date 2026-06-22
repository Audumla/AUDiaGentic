"""Codex config.toml language server format handlers.

Stores language server entries under `[language_servers.<language>]` in
`.codex/config.toml`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomllib

from audiagentic.foundation.contracts.errors import AudiaGenticError

from ...descriptors.base import LanguageServerEntry

_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _format_key(key: str) -> str:
    if _BARE_KEY_RE.fullmatch(key):
        return key
    if "'" not in key:
        return f"'{key}'"
    return f'"{key}"'


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        items = ", ".join(_format_scalar(item) for item in value)
        return f"[{items}]"
    if isinstance(value, dict):
        return _format_inline_table(value)
    raise AudiaGenticError(
        code="VAL-PROV-CODEX-LSP-001",
        kind="providers-codex",
        message=f"unsupported value type: {type(value).__name__}",
        details={"type": type(value).__name__},
    )


def _format_inline_table(d: dict[str, Any]) -> str:
    parts = []
    for k, v in d.items():
        parts.append(f"{_format_key(k)} = {_format_scalar(v)}")
    return "{" + ", ".join(parts) + "}"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    except OSError:
        return {}


def _save_toml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    _write_table(lines, (), data)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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


def read_language_servers_codex(path: Path) -> dict[str, LanguageServerEntry]:
    data = _load_toml(path)
    servers = data.get("language_servers", {})
    if not isinstance(servers, dict):
        return {}
    result: dict[str, LanguageServerEntry] = {}
    for lang, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        result[lang] = LanguageServerEntry(
            language=lang,
            command=cfg.get("command", []),
            file_extensions=cfg.get("file_extensions", []),
            settings=cfg.get("settings", {}),
        )
    return result


def write_language_servers_codex(path: Path, entries: dict[str, LanguageServerEntry]) -> None:
    existing = _load_toml(path)
    servers = existing.setdefault("language_servers", {})
    if not isinstance(servers, dict):
        servers = {}
        existing["language_servers"] = servers
    for lang, entry in entries.items():
        current = servers.get(lang, {})
        if not isinstance(current, dict):
            current = {}
        current["command"] = entry.command
        current["file_extensions"] = entry.file_extensions
        if entry.settings:
            current["settings"] = entry.settings
        servers[lang] = current
    _save_toml(path, existing)


def remove_language_servers_codex(path: Path, language: str) -> bool:
    if not path.exists():
        return False
    existing = _load_toml(path)
    servers = existing.get("language_servers", {})
    if not isinstance(servers, dict) or language not in servers:
        return False
    del servers[language]
    # Drop the table entirely when the last managed server is gone, rather than
    # leaving an empty [language_servers].
    if not servers:
        existing.pop("language_servers", None)
    _save_toml(path, existing)
    return True
