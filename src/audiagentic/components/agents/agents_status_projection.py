"""AS38 — Public status projection adapter.

Maps SH07's public request-status record (a dict) plus an optional AS21
SessionLifecycleDecision into an AS37 AgentStatusSnapshot. Durable SH07
terminal state always wins over an ephemeral AS21 decision.

Pure function, no I/O, no gateway/store imports beyond reading a plain dict.
"""
from __future__ import annotations

import datetime

from audiagentic.components.agents.agents_session_lifecycle_projection import (
    SessionLifecycleDecision,
    snapshot_from_decision,
)
from audiagentic.foundation.transports.agent_status import (
    AgentLifecycle,
    AgentOutcome,
    AgentStatusScope,
    AgentStatusSnapshot,
)

# ---------------------------------------------------------------------------
# Durable state → outcome mapping (SH07 authority)
# ---------------------------------------------------------------------------

_DURABLE_OUTCOME_MAP: dict[str, AgentOutcome] = {
    "completed": AgentOutcome.SUCCESS,
    "failed": AgentOutcome.FAILED,
    "cancelled": AgentOutcome.CANCELLED,
    "interrupted": AgentOutcome.INTERRUPTED,
}


def _now_iso() -> str:
    """Current UTC timestamp as ISO-8601 string."""
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

def snapshot_for_request(
    record: dict,
    *,
    decision: SessionLifecycleDecision | None = None,
) -> AgentStatusSnapshot:
    """Project a public SH07 request-status record (+ optional AS21 decision)
    into an AgentStatusSnapshot.

    Priority order:
        1. Durable terminal state in the record (completed/failed/cancelled/
           interrupted) always wins — SH07 is the source of truth for whether
           a request finished.
        2. When no durable terminal state, an AS21 decision if available.
        3. When neither, UNKNOWN with no outcome and no decisions.

    Critical invariant: interrupted → AgentOutcome.INTERRUPTED +
    AgentLifecycle.TERMINAL (never CANCELLED, never FAILED, never a distinct
    lifecycle value).
    """
    state = record.get("state")
    request_id = record.get("request-id")
    session_id = record.get("session-id")

    # -- Case 1: durable terminal state always wins -------------------------
    if state in _DURABLE_OUTCOME_MAP:
        return AgentStatusSnapshot(
            scope=AgentStatusScope.EXECUTION_REQUEST,
            lifecycle=AgentLifecycle.TERMINAL,
            outcome=_DURABLE_OUTCOME_MAP[state],
            wait_reason=None,
            decisions=None,
            request_id=request_id,
            session_id=session_id,
            turn_id=None,
            generation=None,
            attempt=record.get("attempt-epoch"),
            observed_at=record.get("finished-at") or record.get("updated-at"),
            projected_at=_now_iso(),
        )

    # -- Case 2: no durable terminal state but an AS21 decision is available
    if decision is not None:
        return snapshot_from_decision(
            decision,
            scope=AgentStatusScope.EXECUTION_REQUEST,
            request_id=request_id,
            session_id=session_id,
        )

    # -- Case 3a: queued state → PENDING -----------------------------------
    if state == "queued":
        return AgentStatusSnapshot(
            scope=AgentStatusScope.EXECUTION_REQUEST,
            lifecycle=AgentLifecycle.PENDING,
            outcome=None,
            wait_reason=None,
            decisions=None,
            request_id=request_id,
            session_id=session_id,
            turn_id=None,
            generation=None,
            attempt=None,
            observed_at=None,
            projected_at=_now_iso(),
        )

    # -- Case 3b: no durable terminal state, no decision → UNKNOWN ----------
    return AgentStatusSnapshot(
        scope=AgentStatusScope.EXECUTION_REQUEST,
        lifecycle=AgentLifecycle.UNKNOWN,
        outcome=None,
        wait_reason=None,
        decisions=None,
        request_id=request_id,
        session_id=session_id,
        turn_id=None,
        generation=None,
        attempt=None,
        observed_at=None,
        projected_at=_now_iso(),
    )
