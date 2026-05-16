"""Project release bootstrap orchestration."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from audiagentic.paths import REPO_ROOT
from audiagentic.release.audit import generate_audit_and_checkin
from audiagentic.release.current_summary import regenerate_current_release
from audiagentic.release.release_please import ensure_release_please_baseline
from audiagentic.release.sync import sync_current_release_ledger
from audiagentic.runtime.lifecycle.baseline_sync import ensure_project_layout, sync_managed_baseline
from audiagentic.runtime.lifecycle.detector import detect_installed_state


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _provider_summary(project_root: Path) -> dict[str, str]:
    provider_path = project_root / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    if not provider_path.exists():
        return {}
    payload = yaml.safe_load(provider_path.read_text(encoding="utf-8")) or {}
    providers = payload.get("providers", {})
    summary: dict[str, str] = {}
    for provider_id, config in providers.items():
        enabled = True
        if isinstance(config, dict):
            enabled = bool(config.get("enabled", True))
        summary[str(provider_id)] = "configured" if enabled else "disabled"
    return summary


def bootstrap_release_workflow(project_root: Path, *, release_id: str = "rel_0001") -> dict[str, Any]:
    project_root = project_root.resolve()
    ensure_project_layout(project_root)

    from audiagentic.foundation.components.loader import register_all_components
    register_all_components()

    sync_report = sync_managed_baseline(project_root, source_root=REPO_ROOT)
    created_files = list(sync_report.get("created-files", []))

    # Read existing core-lifecycle marker for version continuity
    marker_path = project_root / ".audiagentic" / "components" / "core-lifecycle.yaml"
    current_marker: dict[str, Any] | None = None
    if marker_path.exists():
        current_marker = yaml.safe_load(marker_path.read_text(encoding="utf-8")) or {}

    installation_kind = "fresh" if current_marker is None else "update"
    current_version = (current_marker or {}).get("version") or "0.1.0"
    now = _now_timestamp()

    updated_marker: dict[str, Any] = {
        "component-id": "core-lifecycle",
        "enabled": True,
        "installation-kind": installation_kind,
        "installed-at": (current_marker or {}).get("installed-at", now),
        "last-lifecycle-action": "release-bootstrap",
        "version": current_version,
    }
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(yaml.dump(updated_marker, default_flow_style=False, sort_keys=True), encoding="utf-8")

    release_state = ensure_release_please_baseline(project_root)
    sync_result = sync_current_release_ledger(project_root)
    summary_path = regenerate_current_release(project_root)
    audit_path, checkin_path = generate_audit_and_checkin(project_root)

    installed_state = detect_installed_state(project_root)
    return {
        "contract-version": "v1",
        "status": "success",
        "release-id": release_id,
        "installed-state": installed_state.state,
        "created-files": created_files,
        "baseline-sync-report": sync_report,
        "marker-path": str(marker_path),
        "release-workflow-state": release_state.get("state"),
        "release-workflow-warnings": release_state.get("warnings", []),
        "synced-fragments": sync_result.fragment_count,
        "current-release-path": str(summary_path),
        "audit-path": str(audit_path),
        "checkin-path": str(checkin_path),
    }
