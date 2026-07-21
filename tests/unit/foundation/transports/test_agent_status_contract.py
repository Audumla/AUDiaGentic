"""AS37 stage-1 — foundation-neutral agent status projection types.

Tests frozen/immutable types, enum validation, lifecycle/outcome invariants,
and import boundary enforcement. No provider imports, no durable state.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from enum import StrEnum

import pytest

# ── Module under test ───────────────────────────────────────────────────────
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.agent_status import (
    AgentLifecycle,
    AgentOutcome,
    AgentStatusDecisions,
    AgentStatusScope,
    AgentStatusSnapshot,
    AgentWaitReason,
    StatusEvidenceConfidence,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_decisions(
    accepts_new_turn: bool = True,
    session_reusable: bool = True,
    turn_terminal: bool = False,
    dependent_work_releasable: bool = False,
    evidence_confidence: StatusEvidenceConfidence = StatusEvidenceConfidence.VALIDATED,
    reason: str = "test decision",
) -> AgentStatusDecisions:
    return AgentStatusDecisions(
        accepts_new_turn=accepts_new_turn,
        session_reusable=session_reusable,
        turn_terminal=turn_terminal,
        dependent_work_releasable=dependent_work_releasable,
        evidence_confidence=evidence_confidence,
        reason=reason,
    )

def _make_snapshot(
    scope: AgentStatusScope = AgentStatusScope.SESSION,
    lifecycle: AgentLifecycle = AgentLifecycle.ACTIVE,
    outcome: AgentOutcome | None = None,
    wait_reason: AgentWaitReason | None = None,
    decisions: AgentStatusDecisions | None = None,
    request_id: str | None = None,
    session_id: str | None = "sess-1",
    turn_id: str | None = None,
    generation: int | None = None,
    attempt: int | None = None,
    observed_at: str | None = None,
    projected_at: str = "2025-01-01T00:00:00Z",
) -> AgentStatusSnapshot:
    return AgentStatusSnapshot(
        scope=scope,
        lifecycle=lifecycle,
        outcome=outcome,
        wait_reason=wait_reason,
        decisions=decisions,
        request_id=request_id,
        session_id=session_id,
        turn_id=turn_id,
        generation=generation,
        attempt=attempt,
        observed_at=observed_at,
        projected_at=projected_at,
    )

def _assert_val_error(
    exc_info: pytest.ExceptionInfo[AudiaGenticError], pattern: str
) -> None:
    """Assert the caught error is a VAL-STATUS-* validation error."""
    assert exc_info.value.code.startswith("VAL-STATUS-")
    if pattern:
        assert pattern in exc_info.value.message

# ── Enum membership (closed sets) ───────────────────────────────────────────

class TestAgentStatusScope:
    def test_values(self) -> None:
        expected = {"execution-request", "session", "turn", "workflow"}
        actual = {s.value for s in AgentStatusScope}
        assert actual == expected

    def test_is_strenum(self) -> None:
        assert issubclass(AgentStatusScope, StrEnum)

    def test_string_equality(self) -> None:
        assert AgentStatusScope.SESSION == "session"

class TestAgentLifecycle:
    def test_values(self) -> None:
        expected = {
            "pending", "active", "waiting", "completing",
            "available", "terminal", "unknown",
        }
        actual = {s.value for s in AgentLifecycle}
        assert actual == expected

    def test_is_strenum(self) -> None:
        assert issubclass(AgentLifecycle, StrEnum)

    def test_string_equality(self) -> None:
        assert AgentLifecycle.TERMINAL == "terminal"

class TestAgentOutcome:
    def test_values(self) -> None:
        expected = {
            "success", "failed", "cancelled", "interrupted",
            "rejected", "timed-out", "expired", "abandoned",
            "superseded",
        }
        actual = {o.value for o in AgentOutcome}
        assert actual == expected

    def test_is_strenum(self) -> None:
        assert issubclass(AgentOutcome, StrEnum)

    def test_string_equality(self) -> None:
        assert AgentOutcome.SUCCESS == "success"

class TestAgentWaitReason:
    def test_values(self) -> None:
        expected = {
            "permission", "queue-capacity", "retry-backoff",
            "dependency", "child-work", "provider-response",
            "tool-response", "operator-action",
            "recovery-decision", "unknown",
        }
        actual = {r.value for r in AgentWaitReason}
        assert actual == expected

    def test_is_strenum(self) -> None:
        assert issubclass(AgentWaitReason, StrEnum)

    def test_string_equality(self) -> None:
        assert AgentWaitReason.PERMISSION == "permission"

class TestStatusEvidenceConfidence:
    def test_values(self) -> None:
        expected = {
            "validated", "candidate", "contradictory",
            "insufficient", "rejected",
        }
        actual = {c.value for c in StatusEvidenceConfidence}
        assert actual == expected

    def test_is_strenum(self) -> None:
        assert issubclass(StatusEvidenceConfidence, StrEnum)

    def test_string_equality(self) -> None:
        assert StatusEvidenceConfidence.VALIDATED == "validated"

# ── Lifecycle / outcome invariants ─────────────────────────────────────────

class TestTerminalRequiresOutcome:
    def test_terminal_without_outcome_raises(self) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_snapshot(
                lifecycle=AgentLifecycle.TERMINAL,
                outcome=None,
            )
        _assert_val_error(exc_info, "terminal lifecycle requires")

    def test_terminal_with_outcome_succeeds(self) -> None:
        snapshot = _make_snapshot(
            lifecycle=AgentLifecycle.TERMINAL,
            outcome=AgentOutcome.SUCCESS,
        )
        assert snapshot.lifecycle == AgentLifecycle.TERMINAL
        assert snapshot.outcome == AgentOutcome.SUCCESS

    def test_terminal_with_each_outcome_succeeds(self) -> None:
        for outcome in AgentOutcome:
            snapshot = _make_snapshot(
                lifecycle=AgentLifecycle.TERMINAL,
                outcome=outcome,
            )
            assert snapshot.outcome == outcome

class TestNonterminalNoOutcome:
    def test_active_with_outcome_raises(self) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_snapshot(
                lifecycle=AgentLifecycle.ACTIVE,
                outcome=AgentOutcome.SUCCESS,
            )
        _assert_val_error(exc_info, "outcome must be None")

    def test_pending_with_outcome_raises(self) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_snapshot(
                lifecycle=AgentLifecycle.PENDING,
                outcome=AgentOutcome.CANCELLED,
            )
        _assert_val_error(exc_info, "outcome must be None")

    def test_all_non_terminal_reject_outcome(self) -> None:
        non_terminal = [
            AgentLifecycle.PENDING,
            AgentLifecycle.ACTIVE,
            AgentLifecycle.WAITING,
            AgentLifecycle.COMPLETING,
            AgentLifecycle.AVAILABLE,
            AgentLifecycle.UNKNOWN,
        ]
        for lc in non_terminal:
            with pytest.raises(AudiaGenticError):
                _make_snapshot(lifecycle=lc, outcome=AgentOutcome.SUCCESS)

# ── Wait reason validation ─────────────────────────────────────────────────

class TestWaitReason:
    def test_waiting_with_none_wait_reason(self) -> None:
        """Waiting lifecycle without wait_reason is allowed."""
        snapshot = _make_snapshot(
            lifecycle=AgentLifecycle.WAITING,
            wait_reason=None,
        )
        assert snapshot.wait_reason is None

    def test_waiting_with_valid_wait_reason(self) -> None:
        """Waiting lifecycle accepts a valid wait_reason."""
        for reason in AgentWaitReason:
            snapshot = _make_snapshot(
                lifecycle=AgentLifecycle.WAITING,
                wait_reason=reason,
            )
            assert snapshot.wait_reason == reason

# ── Frozen immutability ─────────────────────────────────────────────────────

class TestSnapshotFrozen:
    def test_cannot_mutate_field(self) -> None:
        snapshot = _make_snapshot()
        with pytest.raises(AttributeError):
            snapshot.lifecycle = AgentLifecycle.TERMINAL  # type: ignore[misc]

    def test_is_frozen_dataclass(self) -> None:
        assert is_dataclass(AgentStatusSnapshot)
        # frozen=True dataclasses raise on __setattr__
        snapshot = _make_snapshot()
        with pytest.raises(AttributeError):
            snapshot.scope = AgentStatusScope.SESSION  # type: ignore[misc]

class TestDecisionsFrozen:
    def test_cannot_mutate_field(self) -> None:
        decisions = _make_decisions()
        with pytest.raises(AttributeError):
            decisions.accepts_new_turn = False  # type: ignore[misc]

    def test_is_frozen_dataclass(self) -> None:
        assert is_dataclass(AgentStatusDecisions)

# ── projected_at validation ────────────────────────────────────────────────

class TestProjectedAt:
    def test_empty_string_rejected(self) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_snapshot(projected_at="")
        _assert_val_error(exc_info, "projected_at must be a non-empty string")

# ── Valid snapshots ────────────────────────────────────────────────────────

class TestValidSnapshots:
    def test_minimal_active_snapshot(self) -> None:
        """ACTIVE lifecycle, no outcome, no wait_reason, minimal fields."""
        snapshot = _make_snapshot()
        assert snapshot.lifecycle == AgentLifecycle.ACTIVE
        assert snapshot.outcome is None
        assert snapshot.wait_reason is None
        assert snapshot.decisions is None

    def test_valid_terminal_snapshot(self) -> None:
        """TERMINAL + SUCCESS is valid."""
        snapshot = _make_snapshot(
            lifecycle=AgentLifecycle.TERMINAL,
            outcome=AgentOutcome.SUCCESS,
        )
        assert snapshot.lifecycle == AgentLifecycle.TERMINAL
        assert snapshot.outcome == AgentOutcome.SUCCESS

    def test_snapshot_with_decisions(self) -> None:
        """Snapshot with AS21 decisions is valid."""
        decisions = _make_decisions()
        snapshot = _make_snapshot(decisions=decisions)
        assert snapshot.decisions is not None
        assert snapshot.decisions.accepts_new_turn is True

    def test_all_optional_fields_none(self) -> None:
        """Snapshot with all optional fields as None is valid."""
        snapshot = _make_snapshot(
            session_id=None,
            turn_id=None,
            generation=None,
            attempt=None,
            observed_at=None,
        )
        assert snapshot.session_id is None
        assert snapshot.turn_id is None
        assert snapshot.generation is None
        assert snapshot.attempt is None
        assert snapshot.observed_at is None

# ── Error code constants ───────────────────────────────────────────────────

class TestErrorCodes:
    def test_error_code_values(self) -> None:
        from audiagentic.foundation.transports.agent_status import (
            ERR_STATUS_INVALID_PROJECTED_AT,
            ERR_STATUS_NONTERMINAL_NO_OUTCOME,
            ERR_STATUS_TERMINAL_REQUIRES_OUTCOME,
        )
        assert ERR_STATUS_TERMINAL_REQUIRES_OUTCOME == "VAL-STATUS-001"
        assert ERR_STATUS_NONTERMINAL_NO_OUTCOME == "VAL-STATUS-002"
        assert ERR_STATUS_INVALID_PROJECTED_AT == "VAL-STATUS-003"
