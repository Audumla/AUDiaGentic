"""Job state machine."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.state import jobs_store as store

LEGAL_TRANSITIONS = {
    "created": {"ready"},
    "ready": {"running", "cancelled"},
    "running": {"awaiting-approval", "completed", "failed", "cancelled"},
    "awaiting-approval": {"running", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_transition(current_state: str, new_state: str) -> None:
    allowed = LEGAL_TRANSITIONS.get(current_state)
    if allowed is None:
        raise AudiaGenticError(
            code="JOB-VALIDATION-006",
            kind="validation",
            message="unknown job state",
            details={"state": current_state},
        )
    if new_state not in allowed:
        raise AudiaGenticError(
            code="JOB-BUSINESS-001",
            kind="business-rule",
            message="illegal job state transition",
            details={"from": current_state, "to": new_state},
        )


def transition_job(
    job_record: dict[str, Any],
    new_state: str,
    *,
    now_fn: Callable[[], str] | None = None,
) -> dict[str, Any]:
    ensure_transition(job_record["state"], new_state)
    updated = dict(job_record)
    updated["state"] = new_state
    updated["updated-at"] = (now_fn or _now_timestamp)()
    return updated


def transition_and_persist(
    project_root: Path,
    job_id: str,
    new_state: str,
    *,
    now_fn: Callable[[], str] | None = None,
) -> dict[str, Any]:
    record = store.read_job_record(project_root, job_id)
    updated = transition_job(record, new_state, now_fn=now_fn)
    store.write_job_record(project_root, updated)
    return updated
