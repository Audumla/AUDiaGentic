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
from audiagentic.foundation.event.event_bus import DeliveryMode, get_bus
from audiagentic.foundation.io import atomic_write_json, atomic_write_ndjson
from audiagentic.foundation.logging.context import get_correlation_id
from audiagentic.foundation.time import now_iso_z

JobStoreInterface = types.ModuleType

logger = logging.getLogger(__name__)

# Cross-component mirror for agents-owned gateway topic (BU02).
# Owner: agents/agents_gateway_events.CANCEL_REQUESTED_TOPIC
GW_TOPIC_CANCEL_REQUESTED = "agents.execution.gateway.cancel-requested"


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



def _publish_gateway_cancel_requested(
    project_root: Path,
    job: dict[str, Any],
    correlation_id: str | None = None,
) -> None:
    """Propagate a persisted job cancellation to its owning gateway request (EDJ08).

    Publishes ``agents.execution.gateway.cancel-requested`` for the job's
    gateway-request artifact; no-op when the job has none. Called only after
    the job's transition to ``cancelled`` has persisted — a publish failure is
    dead-lettered and never rolls back the local cancellation. Never raises.
    """
    job_id = job.get("job-id", "")
    request_id: str | None = None
    for artifact in job.get("artifacts") or []:
        if (
            isinstance(artifact, dict)
            and artifact.get("kind") == "gateway-request"
            and isinstance(artifact.get("request-id"), str)
        ):
            request_id = artifact["request-id"]
            break
    if not request_id:
        return

    correlation_id = correlation_id or get_correlation_id() or ""
    try:
        get_bus().publish(
            GW_TOPIC_CANCEL_REQUESTED,
            {
                "project-root": str(project_root),
                "request-id": request_id,
            },
            metadata={"job-id": job_id, "correlation_id": correlation_id},
            mode=DeliveryMode.SYNC,
        )
    except Exception as exc:  # noqa: BLE001 — never roll back a persisted cancellation
        logger.error(
            "Failed to publish gateway cancel request for job %s",
            job_id,
            exc_info=True,
        )
        from audiagentic.components.agent_jobs.dead_letter import write_dead_letter

        error_code = exc.code if isinstance(exc, AudiaGenticError) else "INT-EVT-001"
        try:
            write_dead_letter(
                project_root,
                {
                    "event_type": "agents.execution.gateway.cancel-requested",
                    "payload_summary": f"request-id={request_id} job-id={job_id}",
                    "metadata": {"job-id": job_id, "correlation_id": correlation_id},
                    "trigger_id": "",
                    "job_id": job_id,
                    "error_code": error_code,
                    "error_message": str(exc)[:500],
                    "correlation_id": correlation_id,
                },
            )
        except Exception:  # noqa: BLE001 — dead-letter must never raise
            logger.error(
                "Dead-letter write failed for gateway cancel request of job %s",
                job_id,
                exc_info=True,
            )
        return

    record_job_timeline_event(
        project_root,
        job_id,
        "job.gateway-cancel-requested",
        attributes={"request-id": request_id},
        correlation_id=correlation_id or None,
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
        _publish_gateway_cancel_requested(project_root, job)
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
    _publish_gateway_cancel_requested(project_root, job)
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
