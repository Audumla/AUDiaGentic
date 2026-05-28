"""Release-please workflow management — status, update, and baseline install."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from audiagentic.foundation.io import atomic_write_text

_TEMPLATES = Path(__file__).parent / "templates"

MANAGED_NAME = "release-please.audiagentic.yml"
LEGACY_NAME = "release-please.yml"
LEGACY_SUFFIX = "release-please.legacy-pre-audiagentic.yml"
CANDIDATE_NAME = "release-please.audiagentic.candidate.yml"

_MANAGED_FILES = [
    "release-please-config.json",
    ".release-please-manifest.json",
    ".github/workflows/release.yml",
]

BASELINE_WORKFLOW = """name: release-please

on:
  push:
    branches:
      - main
  pull_request:
  workflow_dispatch:
    inputs:
      release_id:
        description: Project release identifier
        required: false
        default: rel_0001

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    env:
      RELEASE_ID: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.release_id || 'rel_0001' }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install runtime dependencies
        run: python -m pip install --upgrade pip pyyaml jsonschema
      - name: Bootstrap release-managed state
        run: python src/audiagentic/channels/cli/main.py release-bootstrap --project-root . --release-id "$RELEASE_ID"
      - name: Verify installed state
        run: python src/audiagentic/channels/cli/main.py providers-status --project-root .
"""


def _workflow_dir(project_root: Path) -> Path:
    return project_root / ".github" / "workflows"


def status(project_root: Path) -> dict[str, Any]:
    files = {rel: ("present" if (project_root / rel).exists() else "missing") for rel in _MANAGED_FILES}
    manifest_version: str | None = None
    manifest_path = project_root / ".release-please-manifest.json"
    if manifest_path.exists():
        try:
            manifest_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(".")
        except Exception:
            logger.warning("Failed to read release manifest", exc_info=True)

    config_release_type: str | None = None
    config_path = project_root / "release-please-config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            config_release_type = cfg.get("release-type") or cfg.get("packages", {}).get(".", {}).get("release-type")
        except Exception:
            logger.warning("Failed to read release config", exc_info=True)

    return {
        "installed": all(v == "present" for v in files.values()),
        "files": files,
        "current_version": manifest_version,
        "release_type": config_release_type,
        "workflow-state": detect_workflow_state(project_root),
    }


def update_workflow(project_root: Path, branch: str = "main", python_version: str = "3.13") -> dict[str, Any]:
    workflow_path = project_root / ".github" / "workflows" / "release.yml"
    if not workflow_path.exists():
        return {"updated": False, "reason": "workflow not present — run install first"}
    subs = {"__BRANCH__": branch, "__PYTHON_VERSION__": python_version}
    template = (_TEMPLATES / "release.yml").read_text(encoding="utf-8")
    for key, value in subs.items():
        template = template.replace(key, value)
    workflow_path.write_text(template, encoding="utf-8")
    return {"updated": True, "path": str(workflow_path.relative_to(project_root))}


def detect_workflow_state(project_root: Path) -> str:
    workflow_dir = _workflow_dir(project_root)
    managed = workflow_dir / MANAGED_NAME
    legacy = workflow_dir / LEGACY_NAME
    if managed.exists():
        return "managed-unmodified" if managed.read_text(encoding="utf-8") == BASELINE_WORKFLOW else "managed-modified"
    if legacy.exists():
        return "legacy-detected"
    if workflow_dir.exists():
        for path in workflow_dir.glob("release-please*.yml"):
            if path.name not in {MANAGED_NAME, LEGACY_NAME, LEGACY_SUFFIX, CANDIDATE_NAME}:
                return "external-unknown"
    return "absent"


def ensure_baseline(project_root: Path) -> dict[str, Any]:
    workflow_dir = _workflow_dir(project_root)
    managed = workflow_dir / MANAGED_NAME
    legacy = workflow_dir / LEGACY_NAME
    warnings: list[dict[str, str]] = []
    state = detect_workflow_state(project_root)

    if state == "absent":
        atomic_write_text(managed, BASELINE_WORKFLOW)
    elif state == "legacy-detected":
        workflow_dir.mkdir(parents=True, exist_ok=True)
        legacy.replace(workflow_dir / LEGACY_SUFFIX)
        atomic_write_text(managed, BASELINE_WORKFLOW)
        warnings.append({"kind": "legacy-rename", "message": "legacy workflow renamed"})
    elif state == "managed-unmodified":
        atomic_write_text(managed, BASELINE_WORKFLOW)
    elif state in {"managed-modified", "external-unknown"}:
        atomic_write_text(workflow_dir / CANDIDATE_NAME, BASELINE_WORKFLOW)
        warnings.append({"kind": "workflow-preserved", "message": "existing workflow preserved"})

    return {"state": state, "warnings": warnings}
