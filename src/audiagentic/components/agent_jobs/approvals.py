"""Job approvals and timeout handling."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs import jobs_store as store
from audiagentic.components.agent_jobs.reviews import read_review_bundle
from audiagentic.components.agent_jobs.state_machine import transition_and_persist
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

DEFAULT_TTL = timedelta(hours=8)




def _approvals_root(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "approvals"


def _approval_path(project_root: Path, approval_id: str) -> Path:
    return _approvals_root(project_root) / f"{approval_id}.json"


def _validate_approval(payload: dict[str, Any]) -> list[str]:
    return validate_with_schema("approval-request", payload)



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
    requested_at = requested_at or now_iso_z()
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
            code="VAL-APPROVE-001",
            kind="agent-jobs",
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
        except Exception:
            logger.warning("Failed to parse approval file %s", path, exc_info=True)
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
            code="VAL-APPROVE-002",
            kind="agent-jobs",
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
    atomic_write_json(path, payload)
    return payload


def read_approval(project_root: Path, approval_id: str) -> dict[str, Any]:
    path = _approval_path(project_root, approval_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-APPROVE-001",
            kind="agent-jobs",
            message="failed to read approval",
            details={"approval-id": approval_id, "error": str(exc)},
        ) from exc
    issues = _validate_approval(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-APPROVE-003",
            kind="agent-jobs",
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
            code="VAL-APPROVE-004",
            kind="agent-jobs",
            message="approval update failed validation",
            details={"approval-id": approval_id, "issues": issues},
        )
    atomic_write_json(_approval_path(project_root, approval_id), payload)
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
            code="CON-APPROVE-001",
            kind="agent-jobs",
            message="job must be running to request approval",
            details={"job-id": job_id, "state": job["state"]},
        )
    review_bundle_id = job.get("review-bundle-id")
    if review_bundle_id:
        bundle = read_review_bundle(project_root, job_id)
        if bundle["decision"] != "approved":
            raise AudiaGenticError(
                code="CON-APPROVE-002",
                kind="agent-jobs",
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
        requested_at=now_ts or now_iso_z(),
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
    now_ts = now_ts or now_iso_z()
    approval = read_approval(project_root, approval_id)
    if approval["state"] == "pending" and _is_expired(approval, now_ts):
        approval = update_approval_state(project_root, approval_id, "expired")
        transition_and_persist(project_root, job_id, "cancelled")
    elif approval["state"] == "approved":
        transition_and_persist(project_root, job_id, "running")
    elif approval["state"] in {"rejected", "cancelled"}:
        transition_and_persist(project_root, job_id, "cancelled")
    return approval
