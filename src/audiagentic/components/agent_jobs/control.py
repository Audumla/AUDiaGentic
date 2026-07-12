"""Job control and cancellation helpers.

Provides job control request building, persistence, and application logic.
Supports dependency injection for testability while maintaining backward
compatibility with global store access.

Key functions:
- build_job_control_request: Create control request payload
- request_job_control: Submit control request with state validation
- apply_pending_job_control: Apply pending control requests

Dependency injection:
- Functions accept optional `store` parameter for test isolation
- Defaults to global jobs_store for backward compatibility
- Use `from audiagentic.components.agent_jobs import jobs_store` for explicit injection
"""

from __future__ import annotations

import json
import logging

# Type alias for store interface
import types
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs import jobs_store as _default_store
from audiagentic.components.agent_jobs.events import record_job_timeline_event
from audiagentic.components.agent_jobs.paths import (
    job_control_events_path,
    job_control_path,
)
from audiagentic.components.agent_jobs.state_machine import (
    TERMINAL_STATES,
    transition_and_persist,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, atomic_write_ndjson
from audiagentic.foundation.time import now_iso_z

JobStoreInterface = types.ModuleType

logger = logging.getLogger(__name__)


def _record_control_timeline_event(
    project_root: Path,
    job_id: str,
    event_name: str,
    *,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> None:
    attrs: dict[str, Any] = {
        "requested-action": payload.get("requested-action"),
        "result": payload.get("result"),
    }
    record_job_timeline_event(
        project_root,
        job_id,
        event_name,
        attributes=attrs,
        correlation_id=correlation_id,
    )



def _control_path(project_root: Path, job_id: str) -> Path:
    return job_control_path(project_root, job_id)


def _control_events_path(project_root: Path, job_id: str) -> Path:
    return job_control_events_path(project_root, job_id)


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_ndjson(path, [payload], append=True)


def build_job_control_request(
    *,
    job_id: str,
    project_id: str,
    requested_action: str,
    requested_by: str,
    reason: str,
    requested_at: str | None = None,
) -> dict[str, Any]:
    if requested_action not in {"cancel", "stop", "kill"}:
        raise AudiaGenticError(
            code="VAL-CONTROL-001",
            kind="agent-jobs",
            message="unsupported job control action",
            details={"requested-action": requested_action},
        )
    payload = {
        "contract-version": "v1",
        "job-id": job_id,
        "project-id": project_id,
        "requested-action": requested_action,
        "requested-by": requested_by,
        "requested-at": requested_at or now_iso_z(),
        "reason": reason,
        "result": "pending",
        "applied-at": None,
    }
    return payload


def read_job_control(project_root: Path, job_id: str) -> dict[str, Any] | None:
    path = _control_path(project_root, job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-CONTROL-001",
            kind="agent-jobs",
            message="failed to read job control record",
            details={"job-id": job_id, "error": str(exc)},
        ) from exc


def write_job_control(project_root: Path, payload: dict[str, Any]) -> Path:
    path = _control_path(project_root, payload["job-id"])
    atomic_write_json(path, payload)
    return path


def request_job_control(
    project_root: Path,
    payload: dict[str, Any],
    store: JobStoreInterface = _default_store,
) -> dict[str, Any]:
    """Submit job control request with state validation.

    Checks job state and applies control request appropriately:
    - Terminal states: Ignore request, mark as ignored
    - Ready/awaiting-approval: Transition to cancelled immediately
    - Other states: Mark request as pending for later application

    Args:
        project_root: Project root directory path
        payload: Control request payload with job-id, action, etc.
        store: Job store interface for reading job records (default: global jobs_store)

    Returns:
        Updated payload with result and applied-at fields

    Example:
        >>> payload = build_job_control_request(job_id="job-001", ...)
        >>> result = request_job_control(project_root, payload)
        >>> print(result["result"])  # "applied", "pending", or "ignored"
    """
    job = store.read_job_record(project_root, payload["job-id"])
    if job["state"] in TERMINAL_STATES:
        payload = dict(payload)
        payload["result"] = "ignored"
        payload["applied-at"] = now_iso_z()
        write_job_control(project_root, payload)
        _append_event(
            _control_events_path(project_root, payload["job-id"]),
            {
                "event-type": "job-control-ignored",
                "job-id": payload["job-id"],
                "project-id": payload["project-id"],
                "requested-action": payload["requested-action"],
                "requested-by": payload["requested-by"],
                "requested-at": payload["requested-at"],
                "applied-at": payload["applied-at"],
                "reason": "job already terminal",
            },
        )
        _record_control_timeline_event(
            project_root,
            payload["job-id"],
            "job.control.ignored",
            payload=payload,
        )
        return payload

    payload = dict(payload)
    if job["state"] in {"ready", "awaiting-approval"}:
        transition_and_persist(project_root, payload["job-id"], "cancelled")
        payload["result"] = "applied"
        payload["applied-at"] = now_iso_z()
    else:
        payload["result"] = "pending"
        payload["applied-at"] = None
    write_job_control(project_root, payload)
    _append_event(
        _control_events_path(project_root, payload["job-id"]),
        {
            "event-type": "job-control-requested",
            "job-id": payload["job-id"],
            "project-id": payload["project-id"],
            "requested-action": payload["requested-action"],
            "requested-by": payload["requested-by"],
            "requested-at": payload["requested-at"],
            "reason": payload["reason"],
            "result": payload["result"],
            "applied-at": payload["applied-at"],
        },
    )
    _record_control_timeline_event(
        project_root,
        payload["job-id"],
        "job.control.requested",
        payload=payload,
    )
    return payload


def apply_pending_job_control(
    project_root: Path,
    job_id: str,
    store: JobStoreInterface = _default_store,
) -> dict[str, Any] | None:
    """Apply pending job control request.

    Checks for pending control requests and applies them based on current job state:
    - No control request: Return None
    - Already applied/ignored: Return existing control record
    - Terminal state: Mark as ignored
    - Active state: Transition to cancelled and mark as applied

    Args:
        project_root: Project root directory path
        job_id: Job identifier
        store: Job store interface for reading job records (default: global jobs_store)

    Returns:
        Updated control record or None if no control request exists

    Example:
        >>> control = apply_pending_job_control(project_root, "job-001")
        >>> if control and control["result"] == "applied":
        ...     print("Job cancelled")
    """
    control = read_job_control(project_root, job_id)
    if control is None:
        return None
    if control.get("result") != "pending":
        return control
    if control.get("requested-action") not in {"cancel", "stop", "kill"}:
        return control
    job = store.read_job_record(project_root, job_id)
    if job["state"] in TERMINAL_STATES:
        control["result"] = "ignored"
        control["applied-at"] = now_iso_z()
        write_job_control(project_root, control)
        _append_event(
            _control_events_path(project_root, job_id),
            {
                "event-type": "job-control-ignored",
                "job-id": job_id,
                "project-id": control["project-id"],
                "requested-action": control["requested-action"],
                "requested-by": control["requested-by"],
                "requested-at": control["requested-at"],
                "applied-at": control["applied-at"],
                "reason": "job already terminal",
            },
        )
        _record_control_timeline_event(
            project_root,
            job_id,
            "job.control.ignored",
            payload=control,
        )
        return control
    transition_and_persist(project_root, job_id, "cancelled")
    control["result"] = "applied"
    control["applied-at"] = now_iso_z()
    write_job_control(project_root, control)
    _append_event(
        _control_events_path(project_root, job_id),
        {
            "event-type": "job-control-applied",
            "job-id": job_id,
            "project-id": control["project-id"],
            "requested-action": control["requested-action"],
            "requested-by": control["requested-by"],
            "requested-at": control["requested-at"],
            "applied-at": control["applied-at"],
            "result": control["result"],
        },
    )
    _record_control_timeline_event(
        project_root,
        job_id,
        "job.control.applied",
        payload=control,
    )
    return control
