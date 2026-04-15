"""Job approvals and timeout handling."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.execution.jobs.reviews import read_review_bundle
from audiagentic.execution.jobs.state_machine import transition_and_persist
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.runtime.state import jobs_store as store

DEFAULT_TTL = timedelta(hours=8)


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _approvals_root(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "approvals"


def _approval_path(project_root: Path, approval_id: str) -> Path:
    return _approvals_root(project_root) / f"{approval_id}.json"


def _validate_approval(payload: dict[str, Any]) -> list[str]:
    schema = read_schema("approval-request")
    validator = Draft202012Validator(schema)
    return sorted(error.message for error in validator.iter_errors(payload))


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def build_approval_request(
    *,
    approval_id: str,
    project_id: str,
    kind: str,
    source_kind: str,
    source_id: str,
    summary: str,
    requested_at: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    requested_at = requested_at or _now_timestamp()
    if expires_at is None:
        expires = datetime.fromisoformat(requested_at.replace("Z", "+00:00")) + DEFAULT_TTL
        expires_at = expires.isoformat().replace("+00:00", "Z")
    payload = {
        "contract-version": "v1",
        "approval-id": approval_id,
        "project-id": project_id,
        "kind": kind,
        "source-kind": source_kind,
        "source-id": source_id,
        "summary": summary,
        "state": "pending",
        "requested-at": requested_at,
        "expires-at": expires_at,
    }
    issues = _validate_approval(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-018",
            kind="validation",
            message="approval request failed validation",
            details={"issues": issues},
        )
    return payload


def _list_pending(project_root: Path, project_id: str, kind: str, source_id: str) -> dict[str, Any] | None:
    root = _approvals_root(project_root)
    if not root.exists():
        return None
    for path in root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if payload.get("state") != "pending":
            continue
        if (
            payload.get("project-id") == project_id
            and payload.get("kind") == kind
            and payload.get("source-id") == source_id
        ):
            return payload
    return None


def request_approval(project_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    issues = _validate_approval(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-019",
            kind="validation",
            message="approval request failed validation",
            details={"issues": issues},
        )
    existing = _list_pending(
        project_root,
        payload["project-id"],
        payload["kind"],
        payload["source-id"],
    )
    if existing:
        return existing
    path = _approval_path(project_root, payload["approval-id"])
    _write_atomic(path, payload)
    return payload


def read_approval(project_root: Path, approval_id: str) -> dict[str, Any]:
    path = _approval_path(project_root, approval_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="JOB-IO-002",
            kind="io",
            message="failed to read approval",
            details={"approval-id": approval_id, "error": str(exc)},
        ) from exc
    issues = _validate_approval(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-020",
            kind="validation",
            message="approval failed validation",
            details={"approval-id": approval_id, "issues": issues},
        )
    return payload


def update_approval_state(project_root: Path, approval_id: str, new_state: str) -> dict[str, Any]:
    payload = read_approval(project_root, approval_id)
    payload["state"] = new_state
    issues = _validate_approval(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-021",
            kind="validation",
            message="approval update failed validation",
            details={"approval-id": approval_id, "issues": issues},
        )
    _write_atomic(_approval_path(project_root, approval_id), payload)
    return payload


def _is_expired(approval: dict[str, Any], now_ts: str) -> bool:
    expires_at = approval.get("expires-at")
    if not expires_at:
        return False
    return datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.fromisoformat(
        now_ts.replace("Z", "+00:00")
    )


def request_job_approval(
    project_root: Path,
    *,
    job_id: str,
    project_id: str,
    kind: str,
    summary: str,
    approval_id: str,
    now_ts: str | None = None,
) -> dict[str, Any]:
    job = store.read_job_record(project_root, job_id)
    if job["state"] != "running":
        raise AudiaGenticError(
            code="JOB-BUSINESS-003",
            kind="business-rule",
            message="job must be running to request approval",
            details={"job-id": job_id, "state": job["state"]},
        )
    review_bundle_id = job.get("review-bundle-id")
    if review_bundle_id:
        bundle = read_review_bundle(project_root, job_id)
        if bundle["decision"] != "approved":
            raise AudiaGenticError(
                code="JOB-BUSINESS-005",
                kind="business-rule",
                message="review bundle is not approved",
                details={"job-id": job_id, "decision": bundle["decision"]},
            )
    approval = build_approval_request(
        approval_id=approval_id,
        project_id=project_id,
        kind=kind,
        source_kind="job-service",
        source_id=job_id,
        summary=summary,
        requested_at=now_ts or _now_timestamp(),
        expires_at=None,
    )
    approval = request_approval(project_root, approval)
    transition_and_persist(project_root, job_id, "awaiting-approval")
    return approval


def check_job_approval(
    project_root: Path,
    *,
    job_id: str,
    approval_id: str,
    now_ts: str | None = None,
) -> dict[str, Any]:
    now_ts = now_ts or _now_timestamp()
    approval = read_approval(project_root, approval_id)
    if approval["state"] == "pending" and _is_expired(approval, now_ts):
        approval = update_approval_state(project_root, approval_id, "expired")
        transition_and_persist(project_root, job_id, "cancelled")
    elif approval["state"] == "approved":
        transition_and_persist(project_root, job_id, "running")
    elif approval["state"] in {"rejected", "cancelled"}:
        transition_and_persist(project_root, job_id, "cancelled")
    return approval
