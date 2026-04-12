"""Legacy cutover lifecycle operations."""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.baseline_sync import ensure_project_layout, sync_managed_baseline
from audiagentic.runtime.lifecycle.checkpoints import write_checkpoint
from audiagentic.runtime.lifecycle.detector import detect_installed_state
from audiagentic.runtime.lifecycle.manifest import build_manifest, write_manifest

LEGACY_WORKFLOW = Path(".github/workflows/release-please.yml")
RENAMED_WORKFLOW = Path(".github/workflows/release-please.legacy.yml")


def _write_migration_report(project_root: Path, outcomes: list[dict[str, str]]) -> Path:
    target_dir = project_root / ".audiagentic" / "runtime" / "migration"
    target_dir.mkdir(parents=True, exist_ok=True)
    report_path = target_dir / "report.json"
    report_path.write_text(json.dumps({"outcomes": outcomes}, indent=2), encoding="utf-8")
    return report_path


def apply_cutover(project_root: Path) -> dict:
    state = detect_installed_state(project_root)
    if state.state != "legacy-only":
        raise AudiaGenticError(
            code="LFC-BUSINESS-003",
            kind="business-rule",
            message="cutover requires legacy-only state",
            details={"state": state.state},
        )

    write_checkpoint(project_root, "planned", {"action": "legacy-cutover"})
    write_checkpoint(project_root, "pre-destructive", {"action": "legacy-cutover"})

    ensure_project_layout(project_root)
    sync_report = sync_managed_baseline(project_root)

    legacy_path = project_root / LEGACY_WORKFLOW
    renamed_path = project_root / RENAMED_WORKFLOW
    if legacy_path.exists():
        renamed_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.replace(renamed_path)

    outcomes: list[dict[str, str]] = []
    for path in (
        "docs/releases/CHANGELOG.md",
        "docs/releases/RELEASE_NOTES.md",
        "docs/releases/VERSION_HISTORY.md",
    ):
        full = project_root / path
        if full.exists():
            outcomes.append({"source": path, "result": "skipped-conflict"})
    _write_migration_report(project_root, outcomes)

    manifest_payload = build_manifest(
        installation_kind="cutover",
        current_version="0.1.0",
        previous_version="legacy",
        components={"core-lifecycle": "installed", "release-audit-ledger": "installed"},
        providers={"local-openai": "configured"},
        last_lifecycle_action="legacy-cutover",
    )
    write_manifest(project_root, manifest_payload)

    write_checkpoint(project_root, "post-migration", {"action": "legacy-cutover"})
    write_checkpoint(project_root, "post-cleanup", {"action": "legacy-cutover"})

    return {
        "contract-version": "v1",
        "mode": "apply",
        "status": "success",
        "completed-operations": [
            "ensure-project-layout",
            "sync-managed-baseline",
            "rename-legacy-workflow",
            "write-migration-report",
            "write-manifest",
        ],
        "baseline-sync-report": sync_report,
        "warnings": [],
        "checkpoint-dir": ".audiagentic/runtime/lifecycle/checkpoints",
    }
