"""Fresh install lifecycle operations."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.baseline_sync import ensure_project_layout, sync_managed_baseline
from audiagentic.runtime.lifecycle.components import DEFAULT_VERSION, install_component
from audiagentic.runtime.lifecycle.detector import detect_installed_state


def apply_fresh_install(project_root: Path) -> dict:
    state = detect_installed_state(project_root)
    if state.state != "none":
        raise AudiaGenticError(
            code="LFC-BUSINESS-001",
            kind="business-rule",
            message="fresh install requires empty state",
            details={"state": state.state},
        )

    register_all_components()

    ensure_project_layout(project_root)
    sync_report = sync_managed_baseline(project_root)

    from audiagentic.foundation.components.registry import all_descriptors
    for component_id in all_descriptors():
        kwargs: dict = {"version": DEFAULT_VERSION}
        if component_id == "core-lifecycle":
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
