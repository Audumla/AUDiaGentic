"""Shared atomic file I/O utilities."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text via a temp file + fsync + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
            entries.append(json.loads(line))
    return entries
