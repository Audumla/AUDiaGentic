"""Project release bootstrap orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from audiagentic.runtime.lifecycle.baseline_sync import ensure_project_layout, sync_managed_baseline
from audiagentic.runtime.lifecycle.detector import detect_installed_state
from audiagentic.runtime.lifecycle.manifest import build_manifest, read_manifest, write_manifest
from audiagentic.runtime.release.audit import generate_audit_and_checkin
from audiagentic.runtime.release.current_summary import regenerate_current_release
from audiagentic.runtime.release.release_please import ensure_release_please_baseline
from audiagentic.runtime.release.sync import sync_current_release_ledger

REPO_ROOT = Path(__file__).resolve().parents[4]


def _provider_summary(project_root: Path) -> dict[str, str]:
    provider_path = project_root / ".audiagentic" / "providers.yaml"
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
    audi_root = project_root / ".audiagentic"

    sync_report = sync_managed_baseline(project_root, source_root=REPO_ROOT)
    created_files = list(sync_report.get("created-files", []))

    current_manifest = None
    manifest_path = audi_root / "installed.json"
    if manifest_path.exists():
        current_manifest = read_manifest(project_root)

    installation_kind = "fresh" if current_manifest is None else "update"
    previous_version = None if current_manifest is None else current_manifest.current_version
    current_version = previous_version or "0.1.0"

    manifest_payload = build_manifest(
        installation_kind=installation_kind,
        current_version=current_version,
        previous_version=previous_version,
        components={
            "core-lifecycle": "installed",
            "release-audit-ledger": "installed",
            "release-workflow": "installed",
        },
        providers=_provider_summary(project_root),
        last_lifecycle_action="release-bootstrap",
    )
    write_manifest(project_root, manifest_payload)

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
        "manifest-path": str(manifest_path),
        "release-workflow-state": release_state.get("state"),
        "release-workflow-warnings": release_state.get("warnings", []),
        "synced-fragments": sync_result.fragment_count,
        "current-release-path": str(summary_path),
        "audit-path": str(audit_path),
        "checkin-path": str(checkin_path),
    }
