"""Bridge jobs to release ledger scripts."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.runtime.release.audit import generate_audit_and_checkin
from audiagentic.runtime.release.current_summary import regenerate_current_release
from audiagentic.runtime.release.fragments import record_change_event
from audiagentic.runtime.release.sync import sync_current_release_ledger


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_change_event_from_job(
    job_record: dict[str, Any],
    change_payload: dict[str, Any],
) -> dict[str, Any]:
    required = {
        "event-id",
        "change-class",
        "files",
        "diff-stats",
        "technical-summary",
        "user-summary-candidate",
    }
    missing = sorted(required - set(change_payload.keys()))
    if missing:
        raise AudiaGenticError(
            code="JOB-VALIDATION-022",
            kind="validation",
            message="change payload missing required fields",
            details={"missing": missing},
        )
    return {
        "contract-version": "v1",
        "event-id": change_payload["event-id"],
        "timestamp-utc": change_payload.get("timestamp-utc") or _now_timestamp(),
        "project-id": job_record.get("project-id"),
        "source": {
            "kind": change_payload.get("source-kind") or "job-run",
            "provider-id": job_record.get("provider-id"),
            "surface": change_payload.get("surface"),
            "session-id": change_payload.get("session-id"),
            "job-id": job_record.get("job-id"),
            "packet-id": job_record.get("packet-id"),
        },
        "change-class": change_payload["change-class"],
        "files": change_payload["files"],
        "diff-stats": change_payload["diff-stats"],
        "technical-summary": change_payload["technical-summary"],
        "user-summary-candidate": change_payload["user-summary-candidate"],
        "status": change_payload.get("status", "unreleased"),
    }


def emit_job_change(
    project_root: Path,
    *,
    job_record: dict[str, Any],
    change_payload: dict[str, Any],
) -> dict[str, Any]:
    event = build_change_event_from_job(job_record, change_payload)
    record_result = record_change_event(project_root, event)
    ledger_result = sync_current_release_ledger(project_root)
    summary_path = regenerate_current_release(project_root)
    audit_path, checkin_path = generate_audit_and_checkin(project_root)
    return {
        "event-id": event["event-id"],
        "fragment-status": record_result["status"],
        "ledger-count": ledger_result.fragment_count,
        "summary-path": str(summary_path),
        "audit-path": str(audit_path),
        "checkin-path": str(checkin_path),
    }
