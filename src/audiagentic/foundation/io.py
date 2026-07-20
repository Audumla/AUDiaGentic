"""Shared atomic file I/O utilities."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import make_error_factory

_io_error: Any = make_error_factory("CFG", "IO", "config")

#: os.replace() onto a destination transiently locked by an antivirus/indexer
#: scan can raise PermissionError (WinError 5) on Windows even though nothing
#: in-process holds the file open. Bounded retry only for this exact
#: transient-lock shape — never masks a genuine permission/ownership failure
#: beyond the retry budget.
_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_SECONDS = 0.05


def read_text_with_retry(path: Path, *, encoding: str = "utf-8") -> str:
    """Read through short Windows sharing violations from atomic replacement."""
    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
        try:
            return path.read_text(encoding=encoding)
        except PermissionError:
            if attempt == _REPLACE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_SECONDS)
    raise AssertionError("bounded read retry loop exhausted")


def _ensure_dict(data: Any) -> dict[str, Any]:
    """Return data if it's a dict, otherwise return an empty dict."""
    return data if isinstance(data, dict) else {}


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text via a temp file + fsync + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(_REPLACE_RETRY_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == _REPLACE_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json_file(path: Path) -> dict[str, Any]:
    """Load JSON mapping from path.

    A missing file returns {} — legitimate "nothing here yet". Malformed
    content raises AudiaGenticError instead of silently returning {}: treating
    corruption the same as absence lets the next write silently overwrite and
    discard whatever was actually on disk (RV713).
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _io_error(3, f"Invalid JSON config: {path}", path=str(path)) from exc
    return _ensure_dict(data)


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2, sort_keys: bool = True) -> None:
    """Atomically write a JSON document."""
    atomic_write_text(path, json.dumps(payload, indent=indent, sort_keys=sort_keys))


def atomic_write_ndjson(path: Path, entries: list[dict[str, Any]], *, append: bool = False) -> None:
    """Atomically write newline-delimited JSON entries, optionally appending to existing content."""
    lines = "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in entries)
    if append and path.exists():
        lines = path.read_text(encoding="utf-8") + lines
    atomic_write_text(path, lines)


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                entries.append(obj)
    return entries


def load_yaml_value(path: Path, default: Any = None) -> Any:
    """Load YAML from path.

    Missing files return ``default``. Malformed YAML raises ``AudiaGenticError``
    with the file path. ``None`` payloads normalize to ``default``.
    """
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise _io_error(1, f"Invalid YAML config: {path}", path=str(path)) from exc
    return default if data is None else data


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _io_error(2, f"Invalid YAML config: {label} must be a mapping", label=label)
    return value


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load YAML mapping from path."""
    return require_mapping(load_yaml_value(path, {}), str(path))


def save_yaml_file(
    path: Path,
    payload: Any,
    *,
    sort_keys: bool = False,
    allow_unicode: bool = True,
    atomic: bool = False,
) -> None:
    text = yaml.safe_dump(
        payload,
        sort_keys=sort_keys,
        allow_unicode=allow_unicode,
        default_flow_style=False,
    )
    if atomic:
        atomic_write_text(path, text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
