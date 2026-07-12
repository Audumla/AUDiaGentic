"""Canonical timeline event names and recording helper for agent-jobs.

All job lifecycle timeline entries must use names from ``JOB_TIMELINE_EVENTS``.
New event names are added to this tuple — never rename existing entries.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.observability.timeline import record_timeline_event

__all__ = ["JOB_TIMELINE_EVENTS", "record_job_timeline_event"]

JOB_TIMELINE_EVENTS: tuple[str, ...] = (
    "job.created",
    "job.ready",
    "job.running",
    "job.awaiting-approval",
    "job.completed",
    "job.failed",
    "job.cancelled",
    "job.control.requested",
    "job.control.applied",
    "job.control.ignored",
    "job.dispatch.accepted",
    "job.dispatch.rejected",
    "job.gateway-outcome-received",
    "job.state-propagated",
)

_STATE_TO_EVENT: dict[str, str] = {
    "created": "job.created",
    "ready": "job.ready",
    "running": "job.running",
    "awaiting-approval": "job.awaiting-approval",
    "completed": "job.completed",
    "failed": "job.failed",
    "cancelled": "job.cancelled",
}


def state_to_event_name(state: str) -> str | None:
    """Return the canonical timeline event name for a job state, or None."""
    return _STATE_TO_EVENT.get(state)


def record_job_timeline_event(
    project_root: Path,
    job_id: str,
    event_name: str,
    *,
    state: str | None = None,
    attributes: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Record a single timeline event for a job using the shared observability helper.

    Parameters
    ----------
    project_root:
        Project root directory.
    job_id:
        Job identifier.
    event_name:
        Canonical event name from ``JOB_TIMELINE_EVENTS``.
    state:
        Current or target job state (mirrored in the timeline entry).
    attributes:
        Arbitrary attributes carried as-is into the event record.
    correlation_id:
        Cross-record trace identifier.  Passed to ``record_timeline_event``;
        falls back to thread-local context if not supplied.

    Returns
    -------
    dict[str, Any]
        The constructed timeline record (useful for callers that need the
        timestamp or resolved correlation-id).
    """
    from audiagentic.components.agent_jobs.paths import job_timeline_path

    attrs = dict(attributes) if attributes else {}
    attrs["job-id"] = job_id
    path = job_timeline_path(project_root, job_id)
    return record_timeline_event(
        path,
        component="agent-jobs",
        resource_kind="job",
        resource_id=job_id,
        event=event_name,
        state=state,
        attributes=attrs,
        correlation_id=correlation_id,
    )
