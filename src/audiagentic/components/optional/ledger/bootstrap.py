"""Ledger component bootstrap — initialise layout and regenerate ledger artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from audiagentic.components.optional.ledger.audit import generate_audit_and_checkin
from audiagentic.components.optional.ledger.current_summary import regenerate_current_release
from audiagentic.components.optional.ledger.sync import sync_current_release_ledger
from audiagentic.foundation.components.ids import COMPONENT_PROJECT
from audiagentic.paths import REPO_ROOT
from audiagentic.runtime.lifecycle.baseline_sync import ensure_project_layout, sync_managed_baseline
from audiagentic.runtime.lifecycle.detector import detect_installed_state


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def bootstrap_ledger(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    ensure_project_layout(project_root)

    from audiagentic.foundation.components.loader import register_all_components
    register_all_components()

    sync_report = sync_managed_baseline(project_root, source_root=REPO_ROOT)
    created_files = list(sync_report.get("created-files", []))

    marker_path = project_root / ".audiagentic" / "components" / "project.yaml"
    current_marker: dict[str, Any] | None = None
    if marker_path.exists():
        current_marker = yaml.safe_load(marker_path.read_text(encoding="utf-8")) or {}

    now = _now_timestamp()
    updated_marker: dict[str, Any] = {
        "component-id": COMPONENT_PROJECT,
        "enabled": True,
        "installation-kind": "fresh" if current_marker is None else "update",
        "installed-at": (current_marker or {}).get("installed-at", now),
        "last-lifecycle-action": "ledger-bootstrap",
        "version": (current_marker or {}).get("version") or "0.1.0",
    }
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(yaml.dump(updated_marker, default_flow_style=False, sort_keys=True), encoding="utf-8")

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
