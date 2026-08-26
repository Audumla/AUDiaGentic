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

# Public activity types are deliberately a small, provider-neutral vocabulary.
# The durable activity envelope may retain a provider's normalized phase for
# diagnostics, but normal polling must not turn that into an unbounded
# provider-event channel.  These values describe work a caller can act on or
# present to a human; lifecycle still answers whether the request is running.
_PUBLIC_ACTIVITY_TYPES = frozenset({
    "thinking",
    "searching-web",
    "read-resource",
    "talked-to-app",
    "called-tool",
    "tool-call",
    "tool-requested",
    "tool-result",
    "tool-finished",
    "tool-progress",
    "response-progress",
    "response-observed",
    "response-started",
    "assistant-message",
    "thought",
    "in-progress",
    "submission-proof",
    "response-complete",
})

_ACTIVITY_TYPE_ALIASES = {
    "searching-the-web": "searching-web",
}


def project_activity_type(record: Mapping[str, Any]) -> str | None:
    """Return the latest bounded provider-work type, if one was recorded.

    This is intentionally derived from the durable provider activity bucket,
    never from source names.  A source describes gateway plumbing (for
    example ``session-transport``); it is not useful work progress for a
    caller.  The direct ``phase`` fallback only reads old dashboard records
    written before provider buckets were introduced.
    """
    activity = record.get("activity")
    if not isinstance(activity, Mapping):
        return None
    provider = activity.get("provider")
    phase = provider.get("phase") if isinstance(provider, Mapping) else activity.get("phase")
    if not isinstance(phase, str):
        return None
    normalized = phase.strip().lower().replace("_", "-").replace(" ", "-")
    normalized = _ACTIVITY_TYPE_ALIASES.get(normalized, normalized)
    return normalized if normalized in _PUBLIC_ACTIVITY_TYPES else None


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
        # A sequence without a recognized activity type is still useful: it
        # proves verified work occurred, while an unfamiliar provider phase is
        # deliberately withheld until it has a reviewed public meaning.
        activity_type = project_activity_type(record) if activity_seq else None
        return _compact({
            "task_id": request_id,
            "lifecycle": "active",
            "activity": activity,
            "activity_type": activity_type,
            "activity_seq": activity_seq,
            "activity_at": activity_at,
            "outcome": None,
        })

    raise TaskStatusContractError(f"unrecognized durable task state: {state}")


def _compact(payload: dict[str, object]) -> dict[str, object]:
    """Remove only inapplicable values; preserve false and zero markers."""
    return {key: value for key, value in payload.items() if value is not None}


__all__ = ["TaskStatusContractError", "project_activity_type", "project_task_status_v4"]
