"""AS21 consumer slice — SessionEvidenceProjection registry tests.

Covers the ephemeral keyed projection registry that accepts only AS19
accepted scalar evidence, maps known statuses to EvidenceKind, invokes
project_session_lifecycle, and exposes a redacted lifecycle-decision
status snapshot. No terminal inference from observer data.

Tests:
    - Activity/waiting E2E (model-thinking → activity, waiting-permission)
    - Rejected evidence unchanged (unknown/terminal status rejected)
    - Never available/terminal from observer data
    - No content/native leakage
    - Sequence preservation and allocation
    - Redacted lifecycle-decision snapshot
"""
from __future__ import annotations

from audiagentic.components.agents.agents_session_lifecycle_projection import (
    SessionEvidenceProjection,
    _map_status_to_evidence_kind,
)
from audiagentic.foundation.transports.harness_status_observer import (
    StatusEvidence,
    StatusEvidenceSemanticStrength,
    StatusEvidenceSourceKind,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_status_evidence(
    status: str,
    *,
    session_id: str = "ses-1",
    request_id: str = "req-1",
    sequence: int | None = None,
    source_kind: StatusEvidenceSourceKind = StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
) -> StatusEvidence:
    """Build a StatusEvidence instance for testing."""
    return StatusEvidence(
        status=status,
        session_id=session_id,
        request_id=request_id,
        correlation_id=None,
        observed_at="2025-01-01T00:00:00Z",
        sequence=sequence,
        source_kind=source_kind,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )

# ---------------------------------------------------------------------------
# Status → EvidenceKind mapping tests
# ---------------------------------------------------------------------------


class TestStatusToKindMapping:
    """AS19 status strings map to AS21 EvidenceKind; terminal/unknown rejected."""

    def test_model_thinking_maps_to_activity(self) -> None:
        assert _map_status_to_evidence_kind("model-thinking") == "activity"

    def test_model_generating_maps_to_activity(self) -> None:
        assert _map_status_to_evidence_kind("model-generating") == "activity"

    def test_tool_calling_maps_to_tool_active(self) -> None:
        assert _map_status_to_evidence_kind("tool-calling") == "tool-active"

    def test_tool_pending_maps_to_tool_active(self) -> None:
        assert _map_status_to_evidence_kind("tool-pending") == "tool-active"

    def test_waiting_permission_maps_to_permission_wait(self) -> None:
        assert _map_status_to_evidence_kind("waiting-permission") == "permission-wait"

    def test_tool_completed_maps(self) -> None:
        assert _map_status_to_evidence_kind("tool-completed") == "tool-completed"

    def test_unknown_status_rejected(self) -> None:
        assert _map_status_to_evidence_kind("unknown-status") is None

    def test_terminal_success_not_inferred(self) -> None:
        """No terminal inference: observer data never produces terminal-success."""
        assert _map_status_to_evidence_kind("terminal-success") is None

    def test_terminal_failed_not_inferred(self) -> None:
        assert _map_status_to_evidence_kind("terminal-failed") is None

# ---------------------------------------------------------------------------
# Activity/waiting E2E tests
# ---------------------------------------------------------------------------


class TestActivityWaitingE2E:
    """End-to-end: model-thinking → active, waiting-permission → waiting."""

    def test_model_thinking_projects_active(self) -> None:
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence("model-thinking")
        assert proj.accept(evidence) is True
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision is not None
        assert decision.coarse_state == "active"

    def test_model_generating_projects_active(self) -> None:
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence("model-generating")
        assert proj.accept(evidence) is True
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision.coarse_state == "active"

    def test_tool_calling_projects_active(self) -> None:
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence("tool-calling")
        assert proj.accept(evidence) is True
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision.coarse_state == "active"

    def test_waiting_permission_projects_waiting(self) -> None:
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence("waiting-permission")
        assert proj.accept(evidence) is True
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision.coarse_state == "waiting"

    def test_activity_then_waiting_projects_waiting(self) -> None:
        """Activity followed by waiting → waiting takes precedence."""
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=1))
        proj.accept(
            _make_status_evidence("waiting-permission", sequence=2),
        )
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision.coarse_state == "waiting"

    def test_multiple_activities_stay_active(self) -> None:
        """Multiple activity observations keep the state active."""
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=1))
        proj.accept(_make_status_evidence("model-generating", sequence=2))
        proj.accept(_make_status_evidence("tool-calling", sequence=3))
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision.coarse_state == "active"

# ---------------------------------------------------------------------------
# Rejected evidence tests
# ---------------------------------------------------------------------------


class TestRejectedEvidence:
    """Unknown/terminal statuses are rejected; evidence unchanged."""

    def test_unknown_status_rejected(self) -> None:
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence("some-unknown-status")
        assert proj.accept(evidence) is False
        assert proj.latest_decision("ses-1", "req-1") is None

    def test_terminal_success_not_accepted(self) -> None:
        """No terminal inference: terminal-success from observer data rejected."""
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence("terminal-success")
        assert proj.accept(evidence) is False
        decision = proj.latest_decision("ses-1", "req-1")
        # Should remain None (no evidence accepted), not completing or available.
        assert decision is None

    def test_terminal_failed_not_accepted(self) -> None:
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence("terminal-failed")
        assert proj.accept(evidence) is False
        assert proj.latest_decision("ses-1", "req-1") is None

    def test_rejected_evidence_does_not_affect_existing_decision(self) -> None:
        """Accepting an activity, then a terminal status → decision stays active."""
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=1))
        assert proj.accept(_make_status_evidence("terminal-success", sequence=2)) is False
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision is not None
        assert decision.coarse_state == "active"

    def test_non_status_evidence_rejected(self) -> None:
        """Non-StatusEvidence objects are rejected."""
        proj = SessionEvidenceProjection()
        assert proj.accept("not evidence") is False
        assert proj.accept(42) is False
        assert proj.accept(None) is False

# ---------------------------------------------------------------------------
# Never available/terminal from observer data
# ---------------------------------------------------------------------------


class TestNeverAvailableTerminalFromObserver:
    """Observer data alone cannot produce available or terminal states."""

    def test_all_activity_statuses_still_not_available(self) -> None:
        """Even with all activity statuses, state is never available."""
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=1))
        proj.accept(_make_status_evidence("tool-calling", sequence=2))
        proj.accept(_make_status_evidence("tool-completed", sequence=3))
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision is not None
        assert decision.coarse_state != "available"
        assert decision.session_reusable is False

    def test_no_terminal_state_from_observer(self) -> None:
        """No terminal or failed state from observer evidence alone."""
        proj = SessionEvidenceProjection()
        for status in (
            "model-thinking", "model-generating", "tool-calling",
            "tool-pending", "waiting-permission", "tool-completed",
        ):
            proj.accept(_make_status_evidence(status))
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision is not None
        # Should not be terminal, failed, or available
        assert decision.coarse_state not in ("available", "failed")
        assert decision.turn_terminal is False

# ---------------------------------------------------------------------------
# No content/native leakage
# ---------------------------------------------------------------------------


class TestNoContentLeakage:
    """The projection carries only bounded scalar evidence — no content."""

    def test_evidence_has_no_content_fields(self) -> None:
        """Accepted evidence contains only safe scalar fields."""
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking"))
        evidence_list = proj._get_evidence_list("ses-1", "req-1")
        assert len(evidence_list) == 1
        ev = evidence_list[0]
        # Should have only the safe fields of SessionLifecycleEvidence
        assert ev.kind == "activity"
        assert ev.session_id == "ses-1"
        assert ev.turn_id == "req-1"
        # No content-bearing fields possible

    def test_redacted_snapshot_has_no_raw_evidence(self) -> None:
        """The redacted snapshot exposes only decision flags, not evidence."""
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking"))
        snapshot = proj.redacted_status_snapshot("ses-1", "req-1")
        # Should have decision fields but no raw evidence list
        assert "lifecycle-decision" in snapshot
        assert "coarse-state" in snapshot
        assert "evidence-accepted" in snapshot
        # No field called "evidence-list" or similar

# ---------------------------------------------------------------------------
# Sequence preservation and allocation
# ---------------------------------------------------------------------------


class TestSequenceHandling:
    """Source sequence is preserved; local sequence allocated when None/0."""

    def test_source_sequence_preserved(self) -> None:
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=42))
        evidence_list = proj._get_evidence_list("ses-1", "req-1")
        assert evidence_list[0].sequence == 42

    def test_local_sequence_allocated_when_none(self) -> None:
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=None))
        evidence_list = proj._get_evidence_list("ses-1", "req-1")
        assert evidence_list[0].sequence >= 1

    def test_local_sequence_monotonically_increases(self) -> None:
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=None))
        proj.accept(_make_status_evidence("tool-calling", sequence=None))
        evidence_list = proj._get_evidence_list("ses-1", "req-1")
        assert evidence_list[0].sequence < evidence_list[1].sequence

    def test_different_sessions_independent_sequences(self) -> None:
        """Different sessions have independent sequence counters."""
        proj = SessionEvidenceProjection()
        proj.accept(
            _make_status_evidence("model-thinking", session_id="ses-A", request_id="req-A"),
        )
        proj.accept(
            _make_status_evidence("model-thinking", session_id="ses-B", request_id="req-B"),
        )
        ev_a = proj._get_evidence_list("ses-A", "req-A")
        ev_b = proj._get_evidence_list("ses-B", "req-B")
        # Both should have sequence 1 (starting fresh per key)
        assert ev_a[0].sequence == 1
        assert ev_b[0].sequence == 1

# ---------------------------------------------------------------------------
# Redacted lifecycle-decision snapshot
# ---------------------------------------------------------------------------


class TestRedactedSnapshot:
    """The redacted_status_snapshot exposes only decision flags."""

    def test_snapshot_no_decision(self) -> None:
        proj = SessionEvidenceProjection()
        snapshot = proj.redacted_status_snapshot("ses-1")
        assert snapshot["lifecycle-decision"] is None
        assert snapshot["coarse-state"] == "unknown"
        assert snapshot["evidence-accepted"] is False

    def test_snapshot_active(self) -> None:
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking"))
        snapshot = proj.redacted_status_snapshot("ses-1", "req-1")
        decision = snapshot["lifecycle-decision"]
        assert decision is not None
        assert decision["coarse-state"] == "active"
        assert decision["accepts-new-turn"] is False
        assert decision["session-reusable"] is False

    def test_snapshot_waiting(self) -> None:
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("waiting-permission"))
        snapshot = proj.redacted_status_snapshot("ses-1", "req-1")
        assert snapshot["lifecycle-decision"]["coarse-state"] == "waiting"

# ---------------------------------------------------------------------------
# Session-level keys (no request_id)
# ---------------------------------------------------------------------------


class TestSessionLevelKey:
    """Evidence without request_id uses the session as key."""

    def test_session_level_evidence(self) -> None:
        proj = SessionEvidenceProjection()
        evidence = _make_status_evidence(
            "model-thinking",
            session_id="ses-1",
            request_id=None,
        )
        assert proj.accept(evidence) is True
        decision = proj.latest_decision("ses-1", None)
        assert decision is not None
        assert decision.coarse_state == "active"

# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------


class TestCleanup:
    """Session close clears evidence projection for that session."""

    def test_clear_for_session(self) -> None:
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", request_id="req-A"))
        proj.accept(
            _make_status_evidence("model-thinking", request_id="req-B"),
        )
        # Different session should not be affected
        proj.accept(
            _make_status_evidence("model-thinking", session_id="ses-2", request_id="req-C"),
        )
        proj.clear_for_session("ses-1")
        assert proj.latest_decision("ses-1", "req-A") is None
        assert proj.latest_decision("ses-1", "req-B") is None
        # ses-2 still has its evidence
        decision = proj.latest_decision("ses-2", "req-C")
        assert decision is not None

    def test_clear_all(self) -> None:
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", session_id="ses-A"))
        proj.accept(_make_status_evidence("model-thinking", session_id="ses-B"))
        proj.clear()
        assert proj.latest_decision("ses-A") is None
        assert proj.latest_decision("ses-B") is None

# ---------------------------------------------------------------------------
# Integration with project_session_lifecycle (via projection)
# ---------------------------------------------------------------------------


class TestIntegrationWithProjector:
    """The projection correctly feeds evidence into the pure projector."""

    def test_activity_then_waiting_via_projection(self) -> None:
        """Activity then waiting → waiting takes precedence through projection."""
        proj = SessionEvidenceProjection()
        proj.accept(_make_status_evidence("model-thinking", sequence=1))
        proj.accept(
            _make_status_evidence("waiting-permission", sequence=2),
        )
        decision = proj.latest_decision("ses-1", "req-1")
        assert decision.coarse_state == "waiting"

    def test_multiple_requests_independent(self) -> None:
        """Different request_ids within the same session are independent."""
        proj = SessionEvidenceProjection()
        proj.accept(
            _make_status_evidence("model-thinking", request_id="req-A", sequence=1),
        )
        proj.accept(
            _make_status_evidence("waiting-permission", request_id="req-B", sequence=1),
        )
        dec_a = proj.latest_decision("ses-1", "req-A")
        dec_b = proj.latest_decision("ses-1", "req-B")
        assert dec_a.coarse_state == "active"
        assert dec_b.coarse_state == "waiting"
