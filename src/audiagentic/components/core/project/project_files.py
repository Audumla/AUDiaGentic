"""File access helpers for the core project component."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_project_file(project_root: Path, relative_path: str) -> dict[str, Any]:
    rel = Path(relative_path)
    if not rel.parts or rel.parts[0] != ".audiagentic":
        raise RuntimeError("path must start with .audiagentic/")

    target = project_root / rel
    try:
        target = target.resolve()
        target.relative_to(project_root.resolve())
    except ValueError as exc:
        raise RuntimeError("path escapes project root") from exc

    if not target.exists():
        raise RuntimeError(f"not found: {relative_path}")
    if not target.is_file():
        raise RuntimeError(f"not a file: {relative_path}")

    text = target.read_text(encoding="utf-8")
    if target.suffix == ".json":
        try:
            return {"path": relative_path, "content": json.loads(text)}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid JSON file: {relative_path}") from exc
    return {"path": relative_path, "content": text}
