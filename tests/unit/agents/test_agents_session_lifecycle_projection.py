"""AS21 -- Session lifecycle projector unit tests (table-driven, deterministic).

Covers active, waiting, completing, available, failed, unknown-empty,
candidate-only, rejected-only, mixed turn IDs, duplicate/lower sequence
contradiction, terminal-before-finalization, finalization-failed,
cancel-with-commit, and identical evidence from two sources.
"""
from __future__ import annotations

from audiagentic.components.agents.agents_session_lifecycle_projection import (
    SessionLifecycleEvidence,
    evidence_from_latest_turn_projection,
    project_session_lifecycle,
    snapshot_from_decision,
)


def _ev(
    kind: str,
    *,
    sequence: int = 1,
    session_id: str = "ses-1",
    turn_id: str = "turn-1",
    validation_state: str = "validated",
    source: str = "transport",
    correlation_id: str | None = None,
    timestamp: str | None = None,
) -> SessionLifecycleEvidence:
    return SessionLifecycleEvidence(
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        kind=kind,  # type: ignore[arg-type] -- Literal narrowed by test intent
        correlation_id=correlation_id,
        timestamp=timestamp,
        validation_state=validation_state,  # type: ignore[arg-type]
        source=source,
    )

# ---------------------------------------------------------------------------
# State coverage
# ---------------------------------------------------------------------------


class TestActive:
    def test_turn_started(self) -> None:
        d = project_session_lifecycle([_ev("turn-started")])
        assert d.coarse_state == "active"
        assert d.accepts_new_turn is False
        assert d.session_reusable is False

    def test_activity(self) -> None:
        d = project_session_lifecycle([_ev("activity")])
        assert d.coarse_state == "active"

    def test_tool_active(self) -> None:
        d = project_session_lifecycle([_ev("tool-active")])
        assert d.coarse_state == "active"


class TestWaiting:
    def test_waiting(self) -> None:
        d = project_session_lifecycle([_ev("waiting")])
        assert d.coarse_state == "waiting"

    def test_permission_wait(self) -> None:
        d = project_session_lifecycle([_ev("permission-wait")])
        assert d.coarse_state == "waiting"

    def test_active_plus_waiting_takes_precedence(self) -> None:
        d = project_session_lifecycle([_ev("activity"), _ev("waiting")])
        assert d.coarse_state == "waiting"


class TestCompleting:
    """Terminal without finalization -> completing (P9 commit-before-available)."""

    def test_terminal_success_no_finalization(self) -> None:
        d = project_session_lifecycle([_ev("terminal-success")])
        assert d.coarse_state == "completing"
        assert d.session_reusable is False
        assert d.dependent_work_releasable is False

    def test_terminal_cancelled_no_finalization(self) -> None:
        d = project_session_lifecycle([_ev("terminal-cancelled")])
        assert d.coarse_state == "completing"


class TestAvailable:
    """Only terminal-success + finalization-committed + blocking-work-cleared."""

    def test_full_available_path(self) -> None:
        d = project_session_lifecycle([
            _ev("terminal-success", sequence=1),
            _ev("finalization-committed", sequence=2),
            _ev("blocking-work-cleared", sequence=3),
        ])
        assert d.coarse_state == "available"
        assert d.accepts_new_turn is True
        assert d.session_reusable is True
        assert d.turn_terminal is True
        assert d.dependent_work_releasable is True

    def test_missing_finalization(self) -> None:
        d = project_session_lifecycle([
            _ev("terminal-success", sequence=1),
            _ev("blocking-work-cleared", sequence=2),
        ])
        assert d.coarse_state != "available"

    def test_missing_blocking_work_cleared(self) -> None:
        d = project_session_lifecycle([
            _ev("terminal-success", sequence=1),
            _ev("finalization-committed", sequence=2),
        ])
        assert d.coarse_state != "available"

    def test_terminal_success_alone_not_available(self) -> None:
        """A terminal protocol event alone never means available (P9)."""
        d = project_session_lifecycle([_ev("terminal-success")])
        assert d.coarse_state == "completing"
        assert d.session_reusable is False

    def test_with_failure_not_available(self) -> None:
        d = project_session_lifecycle([
            _ev("terminal-success", sequence=1),
            _ev("finalization-committed", sequence=2),
            _ev("blocking-work-cleared", sequence=3),
            _ev("transport-error", sequence=4),
        ])
        assert d.coarse_state != "available"


class TestFailed:
    def test_terminal_failed(self) -> None:
        d = project_session_lifecycle([_ev("terminal-failed")])
        assert d.coarse_state == "failed"
        assert d.session_reusable is False

    def test_transport_error(self) -> None:
        d = project_session_lifecycle([_ev("transport-error")])
        assert d.coarse_state == "failed"

    def test_transport_closed(self) -> None:
        d = project_session_lifecycle([_ev("transport-closed")])
        assert d.coarse_state == "failed"

    def test_finalization_failed(self) -> None:
        d = project_session_lifecycle([_ev("finalization-failed")])
        assert d.coarse_state == "failed"
        # dependent_work_releasable is true because finalization has failed
        assert d.dependent_work_releasable is True

    def test_failed_no_finalization_not_releasable(self) -> None:
        """dependent_work_releasable only after finalization committed or failed."""
        d = project_session_lifecycle([_ev("terminal-failed")])
        assert d.dependent_work_releasable is False

    def test_failed_with_finalization_committed_releasable(self) -> None:
        d = project_session_lifecycle([
            _ev("terminal-failed", sequence=1),
            _ev("finalization-committed", sequence=2),
        ])
        assert d.coarse_state == "failed"
        assert d.dependent_work_releasable is True


# ---------------------------------------------------------------------------
# Cancel path
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_with_finalization_not_reusable(self) -> None:
        """terminal-cancelled + finalization-committed without blocking-work-cleared."""
        d = project_session_lifecycle([
            _ev("terminal-cancelled", sequence=1),
            _ev("finalization-committed", sequence=2),
        ])
        assert d.coarse_state != "available" or d.session_reusable is False
        assert d.turn_terminal is True
        assert d.dependent_work_releasable is True

    def test_cancel_with_finalization_and_clearing_is_reusable(self) -> None:
        """terminal-cancelled + finalization-committed + blocking-work-cleared, no failure."""
        d = project_session_lifecycle([
            _ev("terminal-cancelled", sequence=1),
            _ev("finalization-committed", sequence=2),
            _ev("blocking-work-cleared", sequence=3),
        ])
        assert d.coarse_state == "available"
        assert d.session_reusable is True
        assert d.turn_terminal is True
        assert d.dependent_work_releasable is True

    def test_cancel_with_failure_not_reusable(self) -> None:
        """terminal-cancelled + failure evidence blocks reuse."""
        d = project_session_lifecycle([
            _ev("terminal-cancelled", sequence=1),
            _ev("finalization-committed", sequence=2),
            _ev("blocking-work-cleared", sequence=3),
            _ev("transport-error", sequence=4),
        ])
        assert d.session_reusable is False

# ---------------------------------------------------------------------------
# Conservative unknown paths
# ---------------------------------------------------------------------------


class TestConservativeUnknown:
    def test_empty(self) -> None:
        d = project_session_lifecycle([])
        assert d.coarse_state == "unknown"
        assert d.accepts_new_turn is False
        assert d.session_reusable is False
        assert d.dependent_work_releasable is False

    def test_rejected_only(self) -> None:
        d = project_session_lifecycle([
            _ev("turn-started", validation_state="rejected"),
        ])
        assert d.coarse_state == "unknown"
        assert d.evidence_state == "rejected"

    def test_candidate_only(self) -> None:
        d = project_session_lifecycle([
            _ev("turn-started", validation_state="candidate"),
        ])
        assert d.coarse_state == "unknown"
        assert d.evidence_state == "candidate-only"

    def test_mixed_turn_ids(self) -> None:
        d = project_session_lifecycle([
            _ev("turn-started", turn_id="turn-1"),
            _ev("activity", turn_id="turn-2"),
        ])
        assert d.coarse_state == "unknown"
        assert d.dependent_work_releasable is False

    def test_duplicate_lower_sequence(self) -> None:
        """A lower-sequence event after a higher one is contradictory."""
        d = project_session_lifecycle([
            _ev("terminal-success", sequence=5),
            _ev("turn-started", sequence=2),
        ])
        assert d.coarse_state == "unknown"
        assert d.evidence_state == "contradictory"
        assert d.dependent_work_releasable is False

    def test_identical_sequence(self) -> None:
        """Duplicate same-sequence evidence from different sources."""
        d = project_session_lifecycle([
            _ev("turn-started", sequence=1, source="transport"),
            _ev("turn-started", sequence=1, source="hook"),
        ])
        # Same sequence, not lower -- no contradiction. Both validated, same kind.
        assert d.coarse_state == "active"

# ---------------------------------------------------------------------------
# Finalization-failed
# ---------------------------------------------------------------------------


class TestFinalizationFailed:
    def test_finalization_failed_projects_failed(self) -> None:
        d = project_session_lifecycle([_ev("finalization-failed")])
        assert d.coarse_state == "failed"
        assert d.session_reusable is False

    def test_terminal_plus_finalization_failed(self) -> None:
        """Terminal success with finalization-failed = failed, not available."""
        d = project_session_lifecycle([
            _ev("terminal-success", sequence=1),
            _ev("finalization-failed", sequence=2),
        ])
        assert d.coarse_state == "failed"
        assert d.dependent_work_releasable is True

    def test_finalization_failed_with_terminal_failed(self) -> None:
        d = project_session_lifecycle([
            _ev("terminal-failed", sequence=1),
            _ev("finalization-failed", sequence=2),
        ])
        assert d.coarse_state == "failed"
        assert d.dependent_work_releasable is True

# ---------------------------------------------------------------------------
# Identical evidence from two sources
# ---------------------------------------------------------------------------


class TestIdenticalEvidenceTwoSources:
    """Same evidence from different sources projects identically."""

    def test_same_evidence_two_sources(self) -> None:
        ev1 = _ev("turn-started", sequence=1, source="transport")
        ev2 = _ev("turn-started", sequence=1, source="hook")
        d = project_session_lifecycle([ev1, ev2])
        assert d.coarse_state == "active"

    def test_full_available_two_sources(self) -> None:
        """Two sources providing the full available ladder."""
        d = project_session_lifecycle([
            _ev("terminal-success", sequence=1, source="transport"),
            _ev("finalization-committed", sequence=2, source="transport"),
            _ev("blocking-work-cleared", sequence=3, source="hook"),
        ])
        assert d.coarse_state == "available"
        assert d.session_reusable is True

# ---------------------------------------------------------------------------
# Adapter: evidence_from_latest_turn_projection
# ---------------------------------------------------------------------------


class TestAdapterFromProjection:
    def test_basic_turn_started(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "sequence": 1,
        }
        ev = evidence_from_latest_turn_projection(proj)
        assert ev is not None
        assert ev.kind == "turn-started"
        assert ev.session_id == "ses-1"
        assert ev.turn_id == "req-1"

    def test_terminal_success(self) -> None:
        proj = {
            "event": "session.turn.finished",
            "session-id": "ses-1",
            "request-id": "req-1",
        }
        ev = evidence_from_latest_turn_projection(proj)
        assert ev is not None
        assert ev.kind == "terminal-success"

    def test_finalization_committed(self) -> None:
        proj = {
            "event": "session.turn.recorded",
            "session-id": "ses-1",
            "request-id": "req-1",
        }
        ev = evidence_from_latest_turn_projection(proj)
        assert ev is not None
        assert ev.kind == "finalization-committed"

    def test_unknown_session_turn_event(self) -> None:
        """Unknown session.turn.* event maps to activity."""
        proj = {
            "event": "session.turn.model.started",
            "session-id": "ses-1",
            "request-id": "req-1",
        }
        ev = evidence_from_latest_turn_projection(proj)
        assert ev is not None
        assert ev.kind == "activity"

    def test_empty_projection(self) -> None:
        assert evidence_from_latest_turn_projection({}) is None

    def test_none_projection(self) -> None:
        assert evidence_from_latest_turn_projection(None) is None  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# Redaction discipline tests for adapter
# ---------------------------------------------------------------------------

class TestAdapterRedaction:
    """A projection containing prompt/output/tool args/native-topic/provider-ref
    keys must be rejected conservatively."""

    def test_prompt_body_rejected(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "prompt-body": "some prompt",
        }
        assert evidence_from_latest_turn_projection(proj) is None

    def test_output_rejected(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "output": "some output",
        }
        assert evidence_from_latest_turn_projection(proj) is None

    def test_native_topic_rejected(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "native-topic": "turn-started",
        }
        assert evidence_from_latest_turn_projection(proj) is None

    def test_provider_session_ref_rejected(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "provider-session-ref": "prov-ses-1",
        }
        assert evidence_from_latest_turn_projection(proj) is None

    def test_tool_args_rejected(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "tool-args": {"cmd": "echo"},
        }
        assert evidence_from_latest_turn_projection(proj) is None

    def test_binding_rejected(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "binding": {"provider-id": "opencode"},
        }
        assert evidence_from_latest_turn_projection(proj) is None

    def test_underscore_variant_rejected(self) -> None:
        """Underscore variant of redacted keys is also rejected."""
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "prompt_body": "leaked prompt",
        }
        assert evidence_from_latest_turn_projection(proj) is None

    def test_provider_ref_key_rejected(self) -> None:
        proj = {
            "event": "session.turn.started",
            "session-id": "ses-1",
            "request-id": "req-1",
            "provider-ref-key": "ref-abc",
        }
        assert evidence_from_latest_turn_projection(proj) is None

# ---------------------------------------------------------------------------
# AS21 → AS37 adapter: snapshot_from_decision
# ---------------------------------------------------------------------------


class TestSnapshotFromDecision:
    """Adapter tests mapping SessionLifecycleDecision → AgentStatusSnapshot."""

    def test_active_decision_to_active_snapshot(self) -> None:
        decision = project_session_lifecycle([_ev("turn-started")])
        assert decision.coarse_state == "active"
        snap = snapshot_from_decision(decision, session_id="ses-1")
        from audiagentic.foundation.transports.agent_status import (
            AgentLifecycle,
            StatusEvidenceConfidence,
        )

        assert snap.lifecycle == AgentLifecycle.ACTIVE
        assert snap.outcome is None
        assert snap.decisions is not None
        assert snap.decisions.accepts_new_turn is False
        assert snap.decisions.session_reusable is False
        assert snap.decisions.evidence_confidence == StatusEvidenceConfidence.VALIDATED
        assert snap.session_id == "ses-1"

    def test_failed_decision_to_terminal_with_outcome(self) -> None:
        decision = project_session_lifecycle([_ev("terminal-failed")])
        assert decision.coarse_state == "failed"
        snap = snapshot_from_decision(decision)
        from audiagentic.foundation.transports.agent_status import (
            AgentLifecycle,
            AgentOutcome,
        )

        assert snap.lifecycle == AgentLifecycle.TERMINAL
        assert snap.outcome == AgentOutcome.FAILED
        assert snap.decisions is not None
        assert snap.decisions.session_reusable is False

    def test_available_decision_all_flags_true(self) -> None:
        decision = project_session_lifecycle([
            _ev("terminal-success", sequence=1),
            _ev("finalization-committed", sequence=2),
            _ev("blocking-work-cleared", sequence=3),
        ])
        assert decision.coarse_state == "available"
        snap = snapshot_from_decision(decision)
        from audiagentic.foundation.transports.agent_status import AgentLifecycle

        assert snap.lifecycle == AgentLifecycle.AVAILABLE
        assert snap.outcome is None
        assert snap.decisions is not None
        assert snap.decisions.accepts_new_turn is True
        assert snap.decisions.session_reusable is True
        assert snap.decisions.turn_terminal is True
        assert snap.decisions.dependent_work_releasable is True

    def test_contradictory_evidence_unknown_snapshot(self) -> None:
        """Contradictory evidence produces UNKNOWN lifecycle, not terminal."""
        decision = project_session_lifecycle([
            _ev("terminal-success", sequence=5),
            _ev("turn-started", sequence=2),
        ])
        assert decision.coarse_state == "unknown"
        assert decision.evidence_state == "contradictory"
        snap = snapshot_from_decision(decision)
        from audiagentic.foundation.transports.agent_status import (
            AgentLifecycle,
            StatusEvidenceConfidence,
        )

        assert snap.lifecycle == AgentLifecycle.UNKNOWN
        assert snap.outcome is None  # unknown is not terminal
        assert snap.decisions is not None
        assert snap.decisions.evidence_confidence == StatusEvidenceConfidence.CONTRADICTORY

    def test_empty_evidence_unknown_snapshot(self) -> None:
        """Empty evidence produces UNKNOWN lifecycle with insufficient confidence."""
        decision = project_session_lifecycle([])
        assert decision.coarse_state == "unknown"
        assert decision.evidence_state == "insufficient"
        snap = snapshot_from_decision(decision, request_id="req-1", turn_id="turn-1")
        from audiagentic.foundation.transports.agent_status import (
            AgentLifecycle,
            StatusEvidenceConfidence,
        )

        assert snap.lifecycle == AgentLifecycle.UNKNOWN
        assert snap.outcome is None
        assert snap.decisions is not None
        assert snap.decisions.evidence_confidence == StatusEvidenceConfidence.INSUFFICIENT
        assert snap.request_id == "req-1"
        assert snap.turn_id == "turn-1"
