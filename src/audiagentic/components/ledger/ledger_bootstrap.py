"""Ledger component bootstrap — initialise layout and regenerate ledger artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.ledger.audit import generate_audit_and_checkin
from audiagentic.components.ledger.current_summary import regenerate_current_release
from audiagentic.components.ledger.sync import sync_current_release_ledger
from audiagentic.foundation.components.ids import COMPONENT_PROJECT
from audiagentic.foundation.io import load_yaml_file, save_yaml_file
from audiagentic.foundation.lifecycle.baseline_sync import (
    ensure_project_layout,
    sync_managed_baseline,
)
from audiagentic.foundation.lifecycle.components import DEFAULT_VERSION
from audiagentic.foundation.lifecycle.detector import detect_installed_state
from audiagentic.foundation.time import now_iso_z
from audiagentic.paths import REPO_ROOT


def bootstrap_ledger(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    ensure_project_layout(project_root)

    from audiagentic.foundation.components.loader import register_all_components
    register_all_components()

    sync_report = sync_managed_baseline(project_root, source_root=REPO_ROOT)
    created_files_raw = sync_report.get("created-files", [])
    created_files: list[str] = list(created_files_raw) if isinstance(created_files_raw, (list, tuple)) else []

    marker_path = project_root / ".audiagentic" / "components" / "project.yaml"
    current_marker: dict[str, Any] | None = None
    if marker_path.exists():
        current_marker = load_yaml_file(marker_path)

    now = now_iso_z()
    updated_marker: dict[str, Any] = {
        "component-id": COMPONENT_PROJECT,
        "enabled": True,
        "installation-kind": "fresh" if current_marker is None else "update",
        "installed-at": (current_marker or {}).get("installed-at", now),
        "last-lifecycle-action": "ledger-bootstrap",
        "version": (current_marker or {}).get("version") or DEFAULT_VERSION,
    }
    save_yaml_file(marker_path, updated_marker, sort_keys=True)

    sync_result = sync_current_release_ledger(project_root)
    summary_path = regenerate_current_release(project_root)
    audit_path, checkin_path = generate_audit_and_checkin(project_root)

    return {
        "contract-version": "v1",
        "status": "success",
        "installed-state": detect_installed_state(project_root).state,
        "created-files": created_files,
        "baseline-sync-report": sync_report,
        "marker-path": str(marker_path),
        "synced-fragments": sync_result.fragment_count,
        "current-release-path": str(summary_path),
        "audit-path": str(audit_path),
        "checkin-path": str(checkin_path),
    }
