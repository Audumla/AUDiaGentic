"""Release Please baseline workflow management."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

BASELINE_WORKFLOW = """name: release-please

on:
  workflow_dispatch:

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: echo \"Release Please baseline\"
"""

MANAGED_NAME = "release-please.audiagentic.yml"
LEGACY_NAME = "release-please.yml"
LEGACY_SUFFIX = "release-please.legacy-pre-audiagentic.yml"
CANDIDATE_NAME = "release-please.audiagentic.candidate.yml"


def _workflow_dir(project_root: Path) -> Path:
    return project_root / ".github" / "workflows"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def detect_workflow_state(project_root: Path) -> str:
    workflow_dir = _workflow_dir(project_root)
    managed = workflow_dir / MANAGED_NAME
    legacy = workflow_dir / LEGACY_NAME

    if managed.exists():
        content = managed.read_text(encoding="utf-8")
        if content == BASELINE_WORKFLOW:
            return "managed-unmodified"
        return "managed-modified"
    if legacy.exists():
        return "legacy-detected"
    if workflow_dir.exists():
        for path in workflow_dir.glob("release-please*.yml"):
            if path.name not in {MANAGED_NAME, LEGACY_NAME, LEGACY_SUFFIX, CANDIDATE_NAME}:
                return "external-unknown"
    return "absent"


def ensure_release_please_baseline(project_root: Path) -> dict[str, Any]:
    workflow_dir = _workflow_dir(project_root)
    managed = workflow_dir / MANAGED_NAME
    legacy = workflow_dir / LEGACY_NAME
    candidate = workflow_dir / CANDIDATE_NAME
    warnings: list[dict[str, str]] = []

    state = detect_workflow_state(project_root)
    if state == "absent":
        _atomic_write(managed, BASELINE_WORKFLOW)
    elif state == "legacy-detected":
        workflow_dir.mkdir(parents=True, exist_ok=True)
        legacy.replace(workflow_dir / LEGACY_SUFFIX)
        _atomic_write(managed, BASELINE_WORKFLOW)
        warnings.append({"kind": "legacy-rename", "message": "legacy workflow renamed"})
    elif state == "managed-unmodified":
        _atomic_write(managed, BASELINE_WORKFLOW)
    elif state in {"managed-modified", "external-unknown"}:
        _atomic_write(candidate, BASELINE_WORKFLOW)
        warnings.append({"kind": "workflow-preserved", "message": "existing workflow preserved"})
    else:
        warnings.append({"kind": "unknown-state", "message": "workflow state not recognized"})

    return {"state": state, "warnings": warnings}
