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
    from audiagentic.foundation.components.registry import all_descriptors

    # Fresh project install creates only project-scoped core infrastructure.
    # Optional capabilities (including providers) require an explicit component
    # install request; they must not appear enabled merely because a project was
    # initialized.
    descriptors = all_descriptors()
    project_core = {
        component_id
        for component_id, descriptor in descriptors.items()
        if descriptor.core and descriptor.scope == "project"
    }
    sync_report = sync_managed_baseline(
        project_root,
        component_ids=project_core,
        lifecycle_modes={MODE_CREATE_IF_MISSING},
    )

    for component_id in project_core:
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
