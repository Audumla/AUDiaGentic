"""Slim V4 task-status projection for the gateway MCP surface.

The AS92 ``AgentStatusSnapshot`` remains the canonical provider-neutral
status model.  This module only projects that snapshot plus the durable
request state into the deliberately small task-facing polling contract.
It performs no I/O and contains no provider-specific rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from audiagentic.foundation.transports.agent_status import (
    AgentLifecycle,
    AgentOutcome,
    AgentStatusScope,
    AgentStatusSnapshot,
)


class TaskStatusContractError(ValueError):
    """Raised when durable state and the canonical snapshot contradict."""


_TERMINAL_OUTCOMES: dict[str, str] = {
    "completed": AgentOutcome.SUCCESS.value,
    "failed": AgentOutcome.FAILED.value,
    "cancelled": AgentOutcome.CANCELLED.value,
    "interrupted": AgentOutcome.INTERRUPTED.value,
    "rejected": AgentOutcome.REJECTED.value,
    "timed-out": AgentOutcome.TIMED_OUT.value,
    "expired": AgentOutcome.EXPIRED.value,
    "abandoned": AgentOutcome.ABANDONED.value,
    "superseded": AgentOutcome.SUPERSEDED.value,
}

_ACTIVE_SNAPSHOT_LIFECYCLES = {
    AgentLifecycle.ACTIVE,
    AgentLifecycle.WAITING,
    AgentLifecycle.COMPLETING,
    AgentLifecycle.UNKNOWN,
}


def _validate_snapshot(
    record: Mapping[str, Any],
    snapshot: AgentStatusSnapshot | Any | None,
) -> None:
    if snapshot is None:
        return
    if getattr(snapshot, "scope", None) != AgentStatusScope.EXECUTION_REQUEST:
        raise TaskStatusContractError("task status snapshot scope is not execution-request")
    request_id = record.get("request-id")
    if getattr(snapshot, "request_id", None) != request_id:
        raise TaskStatusContractError("task status snapshot request-id does not match request")
    lifecycle = getattr(snapshot, "lifecycle", None)
    outcome = getattr(snapshot, "outcome", None)
    if lifecycle == AgentLifecycle.TERMINAL and outcome is None:
        raise TaskStatusContractError("terminal task status snapshot has no outcome")
    if lifecycle != AgentLifecycle.TERMINAL and outcome is not None:
        raise TaskStatusContractError("non-terminal task status snapshot has an outcome")
    if lifecycle == AgentLifecycle.AVAILABLE:
        raise TaskStatusContractError("execution-request task status cannot be available")


def project_task_status_v4(
    record: Mapping[str, Any],
    canonical_snapshot: AgentStatusSnapshot | Any | None = None,
) -> dict[str, object]:
    """Project one request into the fixed V4 polling contract.

    Inapplicable axes are omitted rather than represented by JSON ``null``.
    Durable terminal state wins; recognized durable
    ``queued``/``dispatching``/``running`` states refine an ``unknown`` AS92
    snapshot without exposing the richer internal snapshot contract.

    ``activity_seq`` and ``activity_at`` are durable progress markers.  The
    sequence advances only when verified provider/owner activity is accepted;
    the timestamp is the time of that activity, not the status-read time.
    """
    request_id = record.get("request-id")
    state = record.get("state")
    if not isinstance(request_id, str) or not request_id:
        raise TaskStatusContractError("task request-id is missing")
    if not isinstance(state, str):
        raise TaskStatusContractError("task durable state is missing")

    activity_seq = record.get("activity-sequence", 0)
    if isinstance(activity_seq, bool) or not isinstance(activity_seq, int) or activity_seq < 0:
        raise TaskStatusContractError("task activity sequence is invalid")
    activity_at = record.get("last-activity-at")
    if activity_at is not None and not isinstance(activity_at, str):
        raise TaskStatusContractError("task activity timestamp is invalid")

    _validate_snapshot(record, canonical_snapshot)
    snapshot_lifecycle = getattr(canonical_snapshot, "lifecycle", None)
    snapshot_outcome = getattr(canonical_snapshot, "outcome", None)

    if state in _TERMINAL_OUTCOMES:
        expected = _TERMINAL_OUTCOMES[state]
        if canonical_snapshot is not None:
            if snapshot_lifecycle != AgentLifecycle.TERMINAL:
                raise TaskStatusContractError("durable terminal state contradicts snapshot lifecycle")
            actual = getattr(snapshot_outcome, "value", snapshot_outcome)
            if actual != expected:
                raise TaskStatusContractError("durable terminal state contradicts snapshot outcome")
        return _compact({
            "task_id": request_id,
            "lifecycle": "terminal",
            "activity": None,
            "activity_seq": activity_seq,
            "activity_at": activity_at,
            "outcome": expected,
        })

    if snapshot_lifecycle == AgentLifecycle.TERMINAL:
        raise TaskStatusContractError("non-terminal durable state has terminal snapshot")

    if state == "queued":
        return _compact({
            "task_id": request_id,
            "lifecycle": "pending",
            "activity": "waiting",
            "activity_seq": activity_seq,
            "activity_at": activity_at,
            "outcome": None,
        })

    if state in {"dispatching", "running"}:
        if snapshot_lifecycle is not None and snapshot_lifecycle not in _ACTIVE_SNAPSHOT_LIFECYCLES:
            raise TaskStatusContractError("durable active state has irreconcilable snapshot lifecycle")
        if record.get("cancel-requested") is True:
            activity = "cancelling"
        elif snapshot_lifecycle == AgentLifecycle.WAITING:
            activity = "waiting"
        elif snapshot_lifecycle == AgentLifecycle.COMPLETING:
            activity = "completing"
        else:
            activity = "running"
        return _compact({
            "task_id": request_id,
            "lifecycle": "active",
            "activity": activity,
            "activity_seq": activity_seq,
            "activity_at": activity_at,
            "outcome": None,
        })

    raise TaskStatusContractError(f"unrecognized durable task state: {state}")


def _compact(payload: dict[str, object]) -> dict[str, object]:
    """Remove only inapplicable values; preserve false and zero markers."""
    return {key: value for key, value in payload.items() if value is not None}


__all__ = ["TaskStatusContractError", "project_task_status_v4"]
