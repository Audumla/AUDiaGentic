"""Uninstall lifecycle operations."""
from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.components import uninstall_all_components
from audiagentic.runtime.lifecycle.detector import detect_installed_state

WORKFLOW_FILES = (
    Path(".github/workflows/release-please.audiagentic.yml"),
)


def apply_uninstall(
    project_root: Path,
    *,
    remove_configs: bool = False,
    remove_workflows: bool = False,
) -> dict:
    register_all_components()

    state = detect_installed_state(project_root)
    if state.state != "installed":
        raise AudiaGenticError(
            code="LFC-BUSINESS-004",
            kind="business-rule",
            message="uninstall requires installed state",
            details={"state": state.state},
        )

    removed = uninstall_all_components(project_root, remove_configs=remove_configs)
    deleted = [str(p.relative_to(project_root)) for p in removed]

    # Safety sweep: remove any runtime state not covered by a component declaration.
    runtime_dir = project_root / ".audiagentic" / "runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)

    if remove_workflows:
        for path in WORKFLOW_FILES:
            full = project_root / path
            if full.exists():
                full.unlink()
                deleted.append(str(path))

    return {
        "contract-version": "v1",
        "mode": "apply",
        "status": "success",
        "completed-operations": ["remove-runtime", "remove-component-files"],
        "deleted-files": deleted,
        "warnings": [],
    }
