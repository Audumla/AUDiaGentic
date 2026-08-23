"""AS38 — Public status projection adapter tests.

Covers the full mapping of SH07 durable states to AgentStatusSnapshot,
the AS21 decision fallback path, and the conservative UNKNOWN default.
The critical invariant: interrupted → AgentOutcome.INTERRUPTED +
AgentLifecycle.TERMINAL (never CANCELLED, never FAILED).
"""

from __future__ import annotations

import pytest

import audiagentic.components.agents.status.status_projection as status_projection

from audiagentic.components.agents.status.session_lifecycle_projection import (
    SessionLifecycleDecision,
)
from audiagentic.components.agents.status.status_projection import (
    snapshot_for_request,
    snapshot_to_mapping,
)
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.transports.agent_status import (
    AgentLifecycle,
    AgentOutcome,
    AgentStatusScope,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(state: str, **kw: object) -> dict:
    """Build a minimal public-status record."""
    base: dict = {
        "request-id": "req-1",
        "session-id": "ses-1",
        "state": state,
        "attempt-epoch": 1,
        "created-at": "2025-01-01T00:00:00+00:00",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Durable terminal state — always wins over any decision
# ---------------------------------------------------------------------------


class TestCompletedRecord:
    def test_completed_to_terminal_success(self) -> None:
        snap = snapshot_for_request(_record("completed"))
        assert snap.scope == AgentStatusScope.EXECUTION_REQUEST
        assert snap.lifecycle == AgentLifecycle.TERMINAL
        assert snap.outcome == AgentOutcome.SUCCESS
        assert snap.decisions is None  # durable wins, no AS21 decisions

    def test_completed_ignores_contradictory_decision(self) -> None:
        """Even a failed decision is overridden by durable completed state."""
        decision = SessionLifecycleDecision(
            coarse_state="failed",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=True,
            dependent_work_releasable=True,
            evidence_state="accepted",
            reason="stale decision",
        )
        snap = snapshot_for_request(_record("completed"), decision=decision)
        assert snap.outcome == AgentOutcome.SUCCESS
        assert snap.decisions is None

    def test_completed_carries_attempt_and_observed(self) -> None:
        rec = _record("completed")
        rec["attempt-epoch"] = 3
        rec["finished-at"] = "2025-06-01T12:00:00+00:00"
        snap = snapshot_for_request(rec)
        assert snap.attempt == 3
        assert snap.observed_at == "2025-06-01T12:00:00+00:00"


# ---------------------------------------------------------------------------


class TestSnapshotSerialization:
    def test_serializes_enums_and_optional_fields(self) -> None:
        mapping = snapshot_to_mapping(snapshot_for_request(_record("completed")))
        assert mapping["scope"] == "execution-request"
        assert mapping["lifecycle"] == "terminal"
        assert mapping["outcome"] == "success"
        assert mapping["decisions"] is None

    def test_mapping_validates_against_canonical_schema(self) -> None:
        mapping = snapshot_to_mapping(snapshot_for_request(_record("completed")))
        assert validate_with_schema("agent-status-snapshot", mapping) == []

    def test_schema_rejects_provider_native_fields(self) -> None:
        mapping = snapshot_to_mapping(snapshot_for_request(_record("queued")))
        mapping["provider-state"] = "generating"
        assert validate_with_schema("agent-status-snapshot", mapping)


class TestFailedRecord:
    def test_failed_to_terminal(self) -> None:
        snap = snapshot_for_request(_record("failed"))
        assert snap.lifecycle == AgentLifecycle.TERMINAL
        assert snap.outcome == AgentOutcome.FAILED


class TestCancelledRecord:
    def test_cancelled_to_terminal(self) -> None:
        snap = snapshot_for_request(_record("cancelled"))
        assert snap.lifecycle == AgentLifecycle.TERMINAL
        assert snap.outcome == AgentOutcome.CANCELLED


class TestRejectedRecord:
    def test_rejected_is_terminal_and_wins_over_stale_decision(self) -> None:
        decision = SessionLifecycleDecision(
            coarse_state="active",
            accepts_new_turn=True,
            session_reusable=True,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="stale active evidence",
        )
        snap = snapshot_for_request(
            _record("rejected", **{"updated-at": "2025-06-01T12:00:00Z"}),
            decision=decision,
        )
        assert snap.lifecycle == AgentLifecycle.TERMINAL
        assert snap.outcome == AgentOutcome.REJECTED
        assert snap.decisions is None

    def test_rejected_uses_updated_at_when_finished_at_is_absent(self) -> None:
        snap = snapshot_for_request(
            _record("rejected", **{"updated-at": "2025-06-01T12:00:00Z"})
        )
        assert snap.observed_at == "2025-06-01T12:00:00Z"
        assert snap.projected_at == "2025-06-01T12:00:00Z"


@pytest.mark.parametrize("state", ["completed", "queued", "running"])
def test_projection_uses_shared_clock_for_final_fallback(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.setattr(status_projection, "now_iso_z", lambda: "2026-08-23T09:00:00Z")
    record = _record(state)
    for key in ("finished-at", "updated-at", "created-at"):
        record.pop(key, None)

    snapshot = snapshot_for_request(record)
    assert snapshot.projected_at == "2026-08-23T09:00:00Z"


class TestInterruptedRecord:
    """Critical invariant: interrupted → INTERRUPTED, never CANCELLED or FAILED."""

    def test_interrupted_to_terminal_interrupted(self) -> None:
        snap = snapshot_for_request(_record("interrupted"))
        assert snap.lifecycle == AgentLifecycle.TERMINAL
        assert snap.outcome == AgentOutcome.INTERRUPTED

    def test_interrupted_is_not_cancelled(self) -> None:
        """Regression: interrupted must not map to CANCELLED."""
        snap = snapshot_for_request(_record("interrupted"))
        assert snap.outcome != AgentOutcome.CANCELLED

    def test_interrupted_is_not_failed(self) -> None:
        """Regression: interrupted must not map to FAILED."""
        snap = snapshot_for_request(_record("interrupted"))
        assert snap.outcome != AgentOutcome.FAILED

    def test_interrupted_ignores_cancelled_decision(self) -> None:
        """Even a cancelled AS21 decision is overridden by durable interrupted."""
        decision = SessionLifecycleDecision(
            coarse_state="failed",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=True,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="stale",
        )
        snap = snapshot_for_request(_record("interrupted"), decision=decision)
        assert snap.outcome == AgentOutcome.INTERRUPTED
        assert snap.decisions is None


# ---------------------------------------------------------------------------
# No durable terminal state — AS21 decision fallback
# ---------------------------------------------------------------------------


class TestRunningWithDecision:
    def test_running_with_active_decision(self) -> None:
        """A running record with an active AS21 decision yields ACTIVE lifecycle."""
        decision = SessionLifecycleDecision(
            coarse_state="active",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="active work evidence",
        )
        snap = snapshot_for_request(_record("running"), decision=decision)
        assert snap.scope == AgentStatusScope.EXECUTION_REQUEST
        assert snap.lifecycle == AgentLifecycle.ACTIVE
        assert snap.outcome is None
        assert snap.decisions is not None
        assert snap.request_id == "req-1"
        assert snap.session_id == "ses-1"

    def test_running_with_waiting_decision(self) -> None:
        decision = SessionLifecycleDecision(
            coarse_state="waiting",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="accepted",
            reason="waiting evidence",
        )
        snap = snapshot_for_request(_record("running"), decision=decision)
        assert snap.lifecycle == AgentLifecycle.WAITING

    def test_running_with_unknown_decision(self) -> None:
        """Unknown coarse state from AS21 maps to UNKNOWN lifecycle."""
        decision = SessionLifecycleDecision(
            coarse_state="unknown",
            accepts_new_turn=False,
            session_reusable=False,
            turn_terminal=False,
            dependent_work_releasable=False,
            evidence_state="insufficient",
            reason="no evidence",
        )
        snap = snapshot_for_request(_record("running"), decision=decision)
        assert snap.lifecycle == AgentLifecycle.UNKNOWN


# ---------------------------------------------------------------------------
# No durable terminal state, no decision — conservative default
# ---------------------------------------------------------------------------


class TestRunningNoDecision:
    def test_running_no_decision_unknown(self) -> None:
        snap = snapshot_for_request(_record("running"))
        assert snap.lifecycle == AgentLifecycle.UNKNOWN
        assert snap.outcome is None
        assert snap.decisions is None

    def test_dispatching_no_decision_unknown(self) -> None:
        snap = snapshot_for_request(_record("dispatching"))
        assert snap.lifecycle == AgentLifecycle.UNKNOWN
        assert snap.outcome is None


# ---------------------------------------------------------------------------
# Queued state — PENDING lifecycle
# ---------------------------------------------------------------------------


class TestQueuedRecord:
    def test_queued_to_pending(self) -> None:
        snap = snapshot_for_request(_record("queued"))
        assert snap.lifecycle == AgentLifecycle.PENDING
        assert snap.outcome is None
        assert snap.decisions is None

    def test_queued_carries_session_id(self) -> None:
        rec = _record("queued")
        rec["session-id"] = "ses-42"
        snap = snapshot_for_request(rec)
        assert snap.session_id == "ses-42"


# ---------------------------------------------------------------------------
# Observed-at fallback logic
# ---------------------------------------------------------------------------


class TestObservedAtFallback:
    def test_uses_finished_at_when_present(self) -> None:
        rec = _record("completed")
        rec["finished-at"] = "2025-06-01T12:00:00+00:00"
        rec["updated-at"] = "2025-06-01T11:59:00+00:00"
        snap = snapshot_for_request(rec)
        assert snap.observed_at == "2025-06-01T12:00:00+00:00"

    def test_falls_back_to_updated_at_when_no_finished_at(self) -> None:
        rec = _record("completed")
        rec["updated-at"] = "2025-06-01T11:59:00+00:00"
        snap = snapshot_for_request(rec)
        assert snap.observed_at == "2025-06-01T11:59:00+00:00"


# ---------------------------------------------------------------------------
# Scope is always EXECUTION_REQUEST
# ---------------------------------------------------------------------------


class TestScopeInvariant:
    @pytest.mark.parametrize(
        "state", ["completed", "failed", "cancelled", "interrupted", "running", "queued"]
    )
    def test_scope_always_execution_request(self, state: str) -> None:
        snap = snapshot_for_request(_record(state))
        assert snap.scope == AgentStatusScope.EXECUTION_REQUEST


# ---------------------------------------------------------------------------
# projected_at is always set
# ---------------------------------------------------------------------------


class TestProjectedAt:
    def test_projected_at_is_set(self) -> None:
        snap = snapshot_for_request(_record("completed"))
        assert isinstance(snap.projected_at, str)
        assert len(snap.projected_at) > 0
