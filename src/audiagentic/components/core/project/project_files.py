"""File access helpers for the core project component."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


def read_project_file(project_root: Path, relative_path: str) -> dict[str, Any]:
    rel = Path(relative_path)
    if not rel.parts or rel.parts[0] != ".audiagentic":
        raise AudiaGenticError(
            code="VAL-PROJFILE-001",
            kind="project",
            message="path must start with .audiagentic/",
            details={"path": relative_path},
        )

    target = project_root / rel
    try:
        target = target.resolve()
        target.relative_to(project_root.resolve())
    except ValueError as exc:
        raise AudiaGenticError(
            code="VAL-PROJFILE-002",
            kind="project",
            message="path escapes project root",
            details={"path": relative_path},
        ) from exc

    if not target.exists():
        raise AudiaGenticError(
            code="RES-PROJFILE-001",
            kind="project",
            message="project file not found",
            details={"path": relative_path},
        )
    if not target.is_file():
        raise AudiaGenticError(
            code="VAL-PROJFILE-003",
            kind="project",
            message="project path is not a file",
            details={"path": relative_path},
        )

    text = target.read_text(encoding="utf-8")
    if target.suffix == ".json":
        try:
            return {"path": relative_path, "content": json.loads(text)}
        except json.JSONDecodeError as exc:
            raise AudiaGenticError(
                code="VAL-PROJFILE-004",
                kind="project",
                message="project JSON file is invalid",
                details={"path": relative_path},
            ) from exc
    return {"path": relative_path, "content": text}
