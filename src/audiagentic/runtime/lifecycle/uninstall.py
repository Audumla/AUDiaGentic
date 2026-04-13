"""Uninstall lifecycle operations."""
from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.checkpoints import write_checkpoint
from audiagentic.runtime.lifecycle.detector import detect_installed_state

WORKFLOW_FILES = (
    Path(".github/workflows/release-please.yml"),
    Path(".github/workflows/release-please.legacy.yml"),
)

CONFIG_FILES = (
    Path(".audiagentic/project.yaml"),
    Path(".audiagentic/components.yaml"),
    Path(".audiagentic/providers.yaml"),
)

STATE_FILES = (Path(".audiagentic/installed.json"),)


def apply_uninstall(
    project_root: Path,
    *,
    remove_configs: bool = False,
    remove_workflows: bool = False,
) -> dict:
    state = detect_installed_state(project_root)
    if state.state != "audiagentic-current":
        raise AudiaGenticError(
            code="LFC-BUSINESS-004",
            kind="business-rule",
            message="uninstall requires audiagentic-current state",
            details={"state": state.state},
        )

    write_checkpoint(project_root, "planned", {"action": "uninstall"})
    write_checkpoint(project_root, "pre-destructive", {"action": "uninstall"})

    runtime_dir = project_root / ".audiagentic" / "runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)

    for path in STATE_FILES:
        full = project_root / path
        if full.exists():
            full.unlink()

    if remove_configs:
        for path in CONFIG_FILES:
            full = project_root / path
            if full.exists():
                full.unlink()

    if remove_workflows:
        for path in WORKFLOW_FILES:
            full = project_root / path
            if full.exists():
                full.unlink()

    return {
        "contract-version": "v1",
        "mode": "apply",
        "status": "success",
        "completed-operations": ["remove-runtime"],
        "warnings": [],
        "checkpoint-dir": ".audiagentic/runtime/lifecycle/checkpoints",
    }
