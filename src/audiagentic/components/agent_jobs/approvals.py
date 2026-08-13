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
from audiagentic.foundation import interaction
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

DEFAULT_TTL = timedelta(hours=8)




def _approvals_root(project_root: Path) -> Path:
    return interaction.interactions_root(project_root)


def _approval_path(project_root: Path, approval_id: str) -> Path:
    return interaction.interaction_path(project_root, approval_id)


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


def _ttl_seconds(requested_at: str, expires_at: str) -> int:
    requested = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return max(1, int((expires - requested).total_seconds()))


def _interaction_to_approval(payload: dict[str, Any]) -> dict[str, Any]:
    answer = payload.get("answer") or {}
    state = payload.get("state")
    choice = answer.get("choice")
    if state == "answered":
        state = choice or "answered"
    requested_at = payload["requested_at"]
    expires = datetime.fromisoformat(requested_at.replace("Z", "+00:00")) + timedelta(
        seconds=int(payload.get("ttl_seconds") or DEFAULT_TTL.total_seconds())
    )
    details = answer.get("details") or {}
    return {
        "contract-version": "v1",
        "approval-id": payload["request_id"],
        "project-id": payload.get("project_id") or details.get("project_id", ""),
        "kind": payload["kind"],
        "source-kind": payload.get("source_kind", ""),
        "source-id": payload.get("source_id", ""),
        "summary": payload["title"],
        "state": state,
        "requested-at": requested_at,
        "expires-at": expires.isoformat().replace("+00:00", "Z"),
    }


def _approval_to_interaction_payload(approval: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": approval["kind"],
        "title": approval["summary"],
        "description": "",
        "choices": ("approved", "rejected"),
        "source_kind": approval["source-kind"],
        "source_id": approval["source-id"],
        "ttl_seconds": _ttl_seconds(approval["requested-at"], approval["expires-at"]),
        "request_id": approval["approval-id"],
    }


def _canonical_work_id(job: dict[str, Any]) -> str | None:
    work_id = job.get("work-id") or job.get("canonical-work-id")
    return work_id if isinstance(work_id, str) and work_id else None


def _request_work_approval(project_root: Path, approval: dict[str, Any], work_id: str) -> dict[str, Any]:
    """Create the interaction and put canonical Work into its approval wait."""
    from audiagentic.components.agents.work.contracts import AgentWorkWaitReason
    from audiagentic.components.agents.work.service import get_work
    from audiagentic.components.agents.work.store import AgentWorkStore

    work = get_work(project_root, work_id)
    existing = _list_pending(
        project_root,
        approval["project-id"],
        approval["kind"],
        approval["source-id"],
    )
    if existing:
        if work.state.value not in {"waiting", "completed", "failed", "cancelled", "rejected"}:
            AgentWorkStore().set_waiting(
                project_root,
                work_id,
                interaction_id=existing["approval-id"],
                reason=AgentWorkWaitReason.APPROVAL,
                expected_revision=work.revision,
            )
        return existing
    interaction_id = interaction.request_interaction(
        project_root=project_root,
        **_approval_to_interaction_payload(approval),
    )
    result = _interaction_to_approval(
        {
            **interaction.read_record(project_root, interaction_id),
            "project_id": approval["project-id"],
        }
    )
    AgentWorkStore().set_waiting(
        project_root,
        work_id,
        interaction_id=interaction_id,
        reason=AgentWorkWaitReason.APPROVAL,
        expected_revision=work.revision,
    )
    return result


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
        approval = _interaction_to_approval(payload)
        if approval.get("state") != "pending":
            continue
        if (
            approval.get("project-id") == project_id
            and approval.get("kind") == kind
            and approval.get("source-id") == source_id
        ):
            return approval
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
    interaction.request_interaction(
        project_root=project_root,
        **_approval_to_interaction_payload(payload),
    )
    record = interaction.read_record(project_root, payload["approval-id"])
    record["project_id"] = payload["project-id"]
    record["requested_at"] = payload["requested-at"]
    interaction.write_record(project_root, record)
    return payload


def read_approval(project_root: Path, approval_id: str) -> dict[str, Any]:
    try:
        payload = interaction.read_record(project_root, approval_id)
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-APPROVE-001",
            kind="agent-jobs",
            message="failed to read approval",
            details={"approval-id": approval_id, "error": str(exc)},
        ) from exc
    approval = _interaction_to_approval(payload)
    issues = _validate_approval(approval)
    if issues:
        raise AudiaGenticError(
            code="VAL-APPROVE-003",
            kind="agent-jobs",
            message="approval failed validation",
            details={"approval-id": approval_id, "issues": issues},
        )
    return approval


def update_approval_state(
    project_root: Path,
    approval_id: str,
    new_state: str,
    *,
    work_id: str | None = None,
) -> dict[str, Any]:
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
    if new_state in {"approved", "rejected", "cancelled"}:
        if work_id is not None:
            from audiagentic.components.agents.work.work_api import answer

            answer(
                project_root,
                work_id,
                choice=new_state,
                details={"project_id": payload["project-id"]},
            )
        else:
            interaction.respond(
                approval_id,
                new_state,
                details={"project_id": payload["project-id"]},
                project_root=project_root,
            )
    elif new_state == "expired":
        record = interaction.read_record(project_root, approval_id)
        record["state"] = "expired"
        interaction.write_record(project_root, record)
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
    work_id: str | None = None,
) -> dict[str, Any]:
    job = None if work_id is not None else store.read_job_record(project_root, job_id)
    work_id = work_id or _canonical_work_id(job or {})
    if work_id is not None:
        approval = build_approval_request(
            approval_id=approval_id,
            project_id=project_id,
            kind=kind,
            source_kind="agent-work",
            source_id=work_id,
            summary=summary,
            requested_at=now_ts or now_iso_z(),
            expires_at=None,
        )
        return _request_work_approval(project_root, approval, work_id)
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
    work_id: str | None = None,
) -> dict[str, Any]:
    now_ts = now_ts or now_iso_z()
    job = None if work_id is not None else store.read_job_record(project_root, job_id)
    work_id = work_id or _canonical_work_id(job or {})
    approval = read_approval(project_root, approval_id)
    if approval["state"] == "pending" and _is_expired(approval, now_ts):
        approval = update_approval_state(project_root, approval_id, "expired")
        if work_id is not None:
            from audiagentic.components.agents.work.service import cancel_work

            cancel_work(project_root, work_id)
        else:
            transition_and_persist(project_root, job_id, "cancelled")
    elif approval["state"] == "approved":
        if work_id is not None:
            from audiagentic.components.agents.work.interactions import resume_after_interaction

            resume_after_interaction(project_root, work_id)
        else:
            transition_and_persist(project_root, job_id, "running")
    elif approval["state"] in {"rejected", "cancelled"}:
        if work_id is not None:
            from audiagentic.components.agents.work.service import cancel_work

            cancel_work(project_root, work_id)
        else:
            transition_and_persist(project_root, job_id, "cancelled")
    return approval
