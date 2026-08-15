"""Operator progress projection for gateway requests (SH07 / RV741).

Pure helper: no I/O, no runtime creation. Derives a bounded, redacted view
from a persisted request record and an optional latest session event.
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Any

STALE_PROGRESS_THRESHOLD_SECONDS = 300


class ProgressDisposition(str, Enum):
    """Operator-facing meaning of a non-terminal request observation.

    These are *diagnostic dispositions*, not request lifecycle states.  In
    particular, ``PROCESSING_UNVERIFIED`` means that the worker is still
    owned and the provider may be quiet; it must never be interpreted as a
    stall or permission to interrupt.
    """

    QUEUED = "queued"
    DISPATCHING = "dispatching"
    PROCESSING_UNVERIFIED = "processing-unverified"
    PROCESSING_VERIFIED = "processing-verified"
    CANCELLATION_REQUESTED = "cancellation-requested"
    STALLED_DIAGNOSTIC = "stalled-diagnostic"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"


class Interruptibility(str, Enum):
    """What an observer may safely do with the current request."""

    ALLOWED = "allowed"
    NOT_SAFE = "not-safe"
    DIAGNOSTIC_ONLY = "diagnostic-only"
    NOT_APPLICABLE = "not-applicable"


def _disposition(record: dict[str, Any]) -> tuple[ProgressDisposition, Interruptibility, str]:
    """Derive an explicit operator disposition from durable evidence.

    Absence of provider activity is intentionally not a stall signal.  A
    running owned attempt without a configured watchdog lease remains
    ``PROCESSING_UNVERIFIED`` and is not safe to interrupt.
    """
    state = record.get("state")
    if isinstance(state, str) and state in _TERMINAL_STATE_TO_PHASE:
        return ProgressDisposition.TERMINAL, Interruptibility.NOT_APPLICABLE, "terminal-request-state"
    if state == "queued":
        return ProgressDisposition.QUEUED, Interruptibility.ALLOWED, "request-awaiting-dispatch"
    if state != "running":
        return ProgressDisposition.UNKNOWN, Interruptibility.NOT_SAFE, "request-state-unrecognized"
    if record.get("cancel-requested"):
        return (
            ProgressDisposition.CANCELLATION_REQUESTED,
            Interruptibility.NOT_SAFE,
            "cancellation-requested-but-not-terminal",
        )
    if record.get("watchdog-state") == "intervention":
        return (
            ProgressDisposition.STALLED_DIAGNOSTIC,
            Interruptibility.DIAGNOSTIC_ONLY,
            "activity-lease-expired-diagnostic-only",
        )
    if record.get("provider-turn-pending") is True:
        return (
            ProgressDisposition.PROCESSING_UNVERIFIED,
            Interruptibility.NOT_SAFE,
            "provider-turn-unresolved-live-attempt",
        )
    if record.get("activity-sequence", 0) or record.get("watchdog-reason") == "verified-activity-renewed":
        return (
            ProgressDisposition.PROCESSING_VERIFIED,
            Interruptibility.NOT_SAFE,
            "verified-provider-activity",
        )
    if record.get("worker-id"):
        return (
            ProgressDisposition.PROCESSING_UNVERIFIED,
            Interruptibility.NOT_SAFE,
            "owned-attempt-awaiting-provider-evidence",
        )
    return ProgressDisposition.DISPATCHING, Interruptibility.NOT_SAFE, "running-without-worker-evidence"

_PHASE_VOCABULARY = frozenset({
    "queued", "claimed", "launching", "prompt-delivered",
    "turn-starting", "model-active", "tool-active",
    "finalizing", "completed", "failed", "cancelled", "rejected",
    "interrupted", "unknown",
})

_TERMINAL_PHASES = frozenset({
    "completed", "failed", "cancelled", "rejected", "interrupted",
})

# Forbidden values that must never appear in the projection output.
_FORBIDDEN_STRINGS = frozenset({
    "prompt-body", "output", "tool_args", "tool-args",
    "provider-binding-ref", "binding-ref",
})

# Keys are the ACP turn-event kinds recorded by _TurnEventProjector /
# _record_turn_timeline in agents_gateway_turn_events.py (session.turn.<kind>).
_EVENT_KIND_TO_PHASE: dict[str, str] = {
    "thought": "model-active",
    "assistant-message": "model-active",
    "tool-call": "tool-active",
    "result": "finalizing",
}

# Fallback for timeline entries that carry an event name but no kind
# attribute (session.turn.started / session.turn.finished / ...).
_EVENT_NAME_TO_PHASE: dict[str, str] = {
    "session.turn.started": "turn-starting",
    "session.turn.finished": "finalizing",
    "session.turn.recorded": "finalizing",
}

_TERMINAL_STATE_TO_PHASE: dict[str, str] = {
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "rejected": "rejected",
    "interrupted": "interrupted",
}


def _parse_ts(value: Any) -> datetime.datetime | None:
    """Best-effort ISO timestamp parse; returns UTC-aware datetime or None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _now_utc() -> datetime.datetime:
    """Current UTC time for tests to override via the ``now`` parameter."""
    return datetime.datetime.now(datetime.timezone.utc)


def project_request_progress(
    record: dict[str, Any],
    *,
    latest_session_event: dict[str, Any] | None = None,
    progress_summary: dict[str, Any] | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return a bounded, redacted progress projection for one request.

    Returns exactly these hyphenated keys:
      phase, running-seconds, last-progress-at, last-progress-source,
      latest-transition, latest-session-event, stale-progress, stale-reason,
      plus optional SH15 richness fields when ``progress_summary`` is provided:
      latest-sequence, event-kind-counts, tool-count-active, tool-count-completed,
      tool-count-failed, assistant-thought-chunk-count, assistant-thought-approx-bytes,
      stop-reason, dropped-events, total-events, callback-disabled.

    Args:
        record: persisted request record (from store.read_public_status or
                store.read_record). Only safe fields are read.
        latest_session_event: optional session evidence dict from the latest
            turn projection (kind and timestamp only).
        progress_summary: optional richer summary built by
            ``build_session_progress_summary`` (SH15). Contains scalar counts,
            tool statuses, byte approximations, and health flags.
        now: current UTC time, defaults to :func:`_now_utc` (inject for tests).

    Returns:
        Projection dict with all keys present. No prompt text, output,
        tool arguments/results, provider refs, auth material, stack traces,
        or raw error objects leak into the result.
    """
    now = now or _now_utc()
    state = record.get("state")

    # --- derive phase ---
    if isinstance(state, str) and state in _TERMINAL_STATE_TO_PHASE:
        phase = _TERMINAL_STATE_TO_PHASE[state]
    elif state == "queued":
        phase = (
            "claimed"
            if record.get("dispatch-owner-epoch")
            else "queued"
        )
    elif state == "running":
        phase = "launching"  # default when no session evidence
    else:
        phase = "unknown"

    # Refine with session event kind (only for non-terminal, non-unknown phases)
    if (
        phase not in _TERMINAL_PHASES
        and phase != "unknown"
        and latest_session_event is not None
    ):
        kind = latest_session_event.get("kind")
        refined = _EVENT_KIND_TO_PHASE.get(kind) if isinstance(kind, str) else None
        if refined is None:
            event_name = latest_session_event.get("event")
            if isinstance(event_name, str):
                refined = _EVENT_NAME_TO_PHASE.get(event_name)
        if refined:
            phase = refined

    # --- derive timestamps ---
    started_at = _parse_ts(record.get("started-at"))
    finished_at = _parse_ts(record.get("finished-at"))

    # Latest request transition timestamp (started-at or attempt timestamps
    # or finished-at, whichever is most recent).
    latest_transition_ts = None
    candidate_ts = []
    if started_at:
        candidate_ts.append(started_at)
    if finished_at:
        candidate_ts.append(finished_at)

    # Attempt timestamps (only the safe ones: started-at, finished-at)
    for attempt in record.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        ts = _parse_ts(attempt.get("started-at"))
        if ts:
            candidate_ts.append(ts)
        ts = _parse_ts(attempt.get("finished-at"))
        if ts:
            candidate_ts.append(ts)

    if candidate_ts:
        latest_transition_ts = max(candidate_ts)

    # Latest session event timestamp (only kind + timestamp, redacted).
    session_event_ts = None
    safe_session_event = None
    if latest_session_event is not None and isinstance(latest_session_event, dict):
        kind = latest_session_event.get("kind")
        ts_val = _parse_ts(latest_session_event.get("timestamp"))
        if isinstance(kind, str) and ts_val:
            session_event_ts = ts_val
            safe_session_event = {"kind": kind, "timestamp": latest_session_event.get("timestamp")}

    # --- last-progress-at / source ---
    last_progress_at = None
    last_progress_source = None

    if latest_transition_ts and session_event_ts:
        if latest_transition_ts >= session_event_ts:
            last_progress_at = latest_transition_ts.isoformat()
            last_progress_source = "request-transition"
        else:
            last_progress_at = session_event_ts.isoformat()
            last_progress_source = "session-event"
    elif latest_transition_ts:
        last_progress_at = latest_transition_ts.isoformat()
        last_progress_source = "request-transition"
    elif session_event_ts:
        last_progress_at = session_event_ts.isoformat()
        last_progress_source = "session-event"

    # --- running-seconds ---
    running_seconds = None
    if started_at:
        delta = now - started_at
        running_seconds = round(delta.total_seconds(), 1)

    # --- latest-transition (record state + timestamp) ---
    latest_transition = None
    if latest_transition_ts is not None:
        latest_transition = {
            "state": state,
            "timestamp": _format_ts(latest_transition_ts),
        }

    # --- stale-progress (diagnostic bool, never for terminal states) ---
    stale_progress = False
    stale_reason = None

    if phase not in _TERMINAL_PHASES and last_progress_at is not None:
        last_pt = _parse_ts(last_progress_at)
        if last_pt is not None:
            elapsed = (now - last_pt).total_seconds()
            if elapsed > STALE_PROGRESS_THRESHOLD_SECONDS:
                stale_progress = True
                stale_reason = "no-turn-evidence-past-threshold"

    disposition, interruptibility, disposition_reason = _disposition(record)

    result: dict[str, Any] = {
        "phase": phase,
        "running-seconds": running_seconds,
        "last-progress-at": last_progress_at,
        "last-progress-source": last_progress_source,
        "latest-transition": latest_transition,
        "latest-session-event": safe_session_event,
        "stale-progress": stale_progress,
        "stale-reason": stale_reason,
        "progress-disposition": disposition.value,
        "interruptibility": interruptibility.value,
        "progress-disposition-reason": disposition_reason,
    }

    provider_turn_pending = record.get("provider-turn-pending")
    if isinstance(provider_turn_pending, bool):
        result["provider-turn-pending"] = provider_turn_pending

    # SH15: include richer progress-summary fields when available
    if progress_summary is not None and isinstance(progress_summary, dict):
        for key in (
            "latest-sequence", "event-kind-counts",
            "tool-count-active", "tool-count-completed", "tool-count-failed",
            "assistant-thought-chunk-count", "assistant-thought-approx-bytes",
            "stop-reason", "dropped-events", "total-events", "callback-disabled",
        ):
            value = progress_summary.get(key)
            if value is not None:
                result[key] = value

    return result


def _format_ts(dt: datetime.datetime) -> str:
    """Format a datetime as an ISO string for JSON output."""
    return dt.isoformat()
