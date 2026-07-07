"""Fresh install lifecycle operations."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.ids import COMPONENT_PROJECT
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.lifecycle.baseline_sync import (
    ensure_project_layout,
    sync_managed_baseline,
)
from audiagentic.foundation.lifecycle.components import DEFAULT_VERSION, install_component
from audiagentic.foundation.lifecycle.detector import detect_installed_state


def apply_fresh_install(project_root: Path) -> dict:
    state = detect_installed_state(project_root)
    if state.state != "none":
        raise AudiaGenticError(
            code="CON-INSTALL-001",
            kind="lifecycle",
            message="fresh install requires empty state",
            details={"state": state.state},
        )

    ensure_project_layout(project_root)
    from audiagentic.foundation.components.base import MODE_CREATE_IF_MISSING
    sync_report = sync_managed_baseline(project_root, lifecycle_modes={MODE_CREATE_IF_MISSING})

    from audiagentic.foundation.components.base import MODE_CREATE_IF_MISSING
    from audiagentic.foundation.components.registry import all_descriptors
    for component_id in all_descriptors():
        kwargs: dict = {"version": DEFAULT_VERSION, "lifecycle_modes": {MODE_CREATE_IF_MISSING}}
        if component_id == COMPONENT_PROJECT:
            kwargs["installation_kind"] = "fresh"
            kwargs["last_lifecycle_action"] = "fresh-install"
        install_component(component_id, project_root, **kwargs)

    return {
        "contract-version": "v1",
        "mode": "apply",
        "status": "success",
        "completed-operations": ["ensure-project-layout", "sync-managed-baseline", "write-component-markers"],
        "baseline-sync-report": sync_report,
        "warnings": [],
    }
