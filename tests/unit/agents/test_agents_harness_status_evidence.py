"""AS19 Stage-2 Slice B: agents-side evidence sink unit tests.

Tests StatusEvidenceSink validation, monotonic dedup, scalar allowlist,
redacted timeline append, and agents.turn.status.observed publish.
No real transport, no Docker.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from audiagentic.components.agents.status.harness_status_evidence import (
    AcceptedEvidence,
    RejectedEvidence,
    StatusEvidenceSink,
)
from audiagentic.foundation.transports.harness_status_observer import (
    StatusEvidence,
    StatusEvidenceSemanticStrength,
    StatusEvidenceSourceKind,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evidence(
    session_id: str = "ses_test_1",
    request_id: str | None = "req_1",
    sequence: int | None = 1,
    status: str = "model-thinking",
    correlation_id: str | None = "obsbnd_binding_1",
) -> StatusEvidence:
    return StatusEvidence(
        status=status,
        session_id=session_id,
        request_id=request_id,
        correlation_id=correlation_id,
        observed_at="2026-07-20T10:00:00Z",
        sequence=sequence,
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )

# ---------------------------------------------------------------------------
# Accepted activity — happy path
# ---------------------------------------------------------------------------

class TestAcceptedActivity:
    """Valid StatusEvidence is accepted, timeline recorded, event published."""

    def test_accepts_valid_evidence(self):
        """A valid evidence with matching session/request is accepted."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,  # no timeline in this test
        )
        evidence = _make_evidence(sequence=1)
        result = sink.accept(evidence)
        assert isinstance(result, AcceptedEvidence)
        assert result.status_evidence is evidence

    def test_accepted_with_none_sequence(self):
        """Evidence with sequence=None is accepted (no ordering)."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        evidence = _make_evidence(sequence=None)
        result = sink.accept(evidence)
        assert isinstance(result, AcceptedEvidence)

    def test_accepted_with_none_request_id(self):
        """Session-level evidence (request_id=None) is accepted when sink expects None."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id=None,
            project_root=None,
        )
        evidence = _make_evidence(request_id=None)
        result = sink.accept(evidence)
        assert isinstance(result, AcceptedEvidence)

    def test_highest_sequence_updated(self):
        """After accepting, highest_sequence tracks the sequence."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        assert sink.highest_sequence is None
        evidence = _make_evidence(sequence=5)
        sink.accept(evidence)
        assert sink.highest_sequence == 5

    def test_timeline_append_called(self):
        """Accept triggers a redacted timeline append when project_root is set."""
        with patch(
            "audiagentic.components.agents.status.harness_status_evidence.session_store"
        ) as mock_store:
            sink = StatusEvidenceSink(
                session_id="ses_test_1",
                request_id="req_1",
                project_root=MagicMock(),
            )
            evidence = _make_evidence(sequence=1)
            result = sink.accept(evidence)
            assert isinstance(result, AcceptedEvidence)
            mock_store.record_session_timeline.assert_called_once()
            call_kwargs = mock_store.record_session_timeline.call_args
            # Verify the event name is session.status.observed
            assert call_kwargs[0][2] == "session.status.observed"

    def test_event_published(self):
        """Accept publishes exactly one agents.turn.status.observed event."""
        with patch(
            "audiagentic.foundation.event.get_bus"
        ) as mock_get_bus:
            mock_bus = MagicMock()
            mock_get_bus.return_value = mock_bus
            sink = StatusEvidenceSink(
                session_id="ses_test_1",
                request_id="req_1",
                correlation_id="corr_1",
                project_root=None,
            )
            evidence = _make_evidence(sequence=1)
            result = sink.accept(evidence)
            assert isinstance(result, AcceptedEvidence)
            mock_bus.publish.assert_called_once()
            call_args = mock_bus.publish.call_args
            # Verify the topic is agents.turn.status.observed
            from audiagentic.components.agents.gateway.event_topics import (
                TURN_STATUS_OBSERVED_TOPIC,
            )
            assert call_args[0][0] == TURN_STATUS_OBSERVED_TOPIC

    def test_no_raw_native_fields_in_timeline(self):
        """Timeline attributes contain only bounded scalar fields."""
        with patch(
            "audiagentic.components.agents.status.harness_status_evidence.session_store"
        ) as mock_store:
            sink = StatusEvidenceSink(
                session_id="ses_test_1",
                request_id="req_1",
                project_root=MagicMock(),
            )
            evidence = _make_evidence(sequence=1)
            sink.accept(evidence)
            call_kwargs = mock_store.record_session_timeline.call_args
            attrs = call_kwargs[1]["attributes"]
            # Only scalar fields should be present
            for key in attrs:
                value = attrs[key]
                assert isinstance(value, (str, int, float, bool)) or value is None

    def test_no_raw_native_fields_in_event(self):
        """Published event payload contains only bounded scalar fields."""
        with patch(
            "audiagentic.foundation.event.get_bus"
        ) as mock_get_bus:
            mock_bus = MagicMock()
            mock_get_bus.return_value = mock_bus
            sink = StatusEvidenceSink(
                session_id="ses_test_1",
                request_id="req_1",
                project_root=None,
            )
            evidence = _make_evidence(sequence=1)
            sink.accept(evidence)
            call_args = mock_bus.publish.call_args
            payload = call_args[0][1]
            for key in payload:
                value = payload[key]
                assert isinstance(value, (str, int, float, bool)) or value is None

# ---------------------------------------------------------------------------
# Monotonic dedup — duplicate and lower sequence rejection
# ---------------------------------------------------------------------------

class TestMonotonicDedupe:
    """Rejects duplicate sequences and lower sequences within a turn."""

    def test_duplicate_sequence_rejected(self):
        """Same sequence rejected as duplicate."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        sink.accept(_make_evidence(sequence=5))
        result = sink.accept(_make_evidence(sequence=5))
        assert isinstance(result, RejectedEvidence)
        assert result.reason == "duplicate-sequence"

    def test_lower_sequence_rejected(self):
        """Lower sequence rejected as out-of-order."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        sink.accept(_make_evidence(sequence=10))
        result = sink.accept(_make_evidence(sequence=3))
        assert isinstance(result, RejectedEvidence)
        assert result.reason == "lower-sequence"

    def test_strictly_increasing_accepted(self):
        """Strictly increasing sequences are all accepted."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        for seq in [1, 3, 5, 7]:
            evidence = _make_evidence(sequence=seq)
            result = sink.accept(evidence)
            assert isinstance(result, AcceptedEvidence)
        assert sink.highest_sequence == 7

    def test_none_sequence_after_int_accepted(self):
        """A None sequence after an int sequence is accepted (None carries no ordering)."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        sink.accept(_make_evidence(sequence=5))
        result = sink.accept(_make_evidence(sequence=None))
        assert isinstance(result, AcceptedEvidence)

    def test_int_sequence_after_none_accepted(self):
        """An int sequence after a None sequence is accepted (no prior ordering)."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        sink.accept(_make_evidence(sequence=None))
        result = sink.accept(_make_evidence(sequence=3))
        assert isinstance(result, AcceptedEvidence)

    def test_invalid_sequence_type_rejected(self):
        """Non-int sequence is rejected as invalid."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        # Create evidence with a string sequence — StatusEvidence accepts it
        # since it's a str, but the sink rejects non-int sequences.
        evidence = _make_evidence(sequence=5)
        # Monkey-patch sequence to be a string (after creation).
        # We use a mutable proxy to simulate bad data.
        class _BadSeqEvidence:
            def __init__(self, ev):
                for k in ev.__dataclass_fields__:
                    setattr(self, k, getattr(ev, k))
                self.sequence = "not-an-int"

        bad_evidence = _BadSeqEvidence(evidence)
        result = sink.accept(bad_evidence)
        assert isinstance(result, RejectedEvidence)
        assert result.reason == "invalid-sequence"

# ---------------------------------------------------------------------------
# Binding mismatch — correlation validation
# ---------------------------------------------------------------------------

class TestBindingMismatch:
    """Rejects evidence with wrong session or request correlation."""

    def test_session_mismatch_rejected(self):
        """Evidence from a different session is rejected."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        evidence = _make_evidence(session_id="ses_wrong")
        result = sink.accept(evidence)
        assert isinstance(result, RejectedEvidence)
        assert result.reason == "binding-mismatch"

    def test_request_mismatch_rejected(self):
        """Evidence from a different request is rejected."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        evidence = _make_evidence(request_id="req_wrong")
        result = sink.accept(evidence)
        assert isinstance(result, RejectedEvidence)
        assert result.reason == "request-mismatch"

    def test_none_request_evidence_with_set_sink_rejected(self):
        """Evi with request_id=None rejected when sink expects a specific request."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        evidence = _make_evidence(request_id=None)
        result = sink.accept(evidence)
        assert isinstance(result, RejectedEvidence)
        assert result.reason == "request-mismatch"

# ---------------------------------------------------------------------------
# Missing / None evidence
# ---------------------------------------------------------------------------

class TestMissingEvidence:
    """Rejects None or missing evidence."""

    def test_none_evidence_rejected(self):
        """None evidence is rejected."""
        sink = StatusEvidenceSink(
            session_id="ses_test_1",
            request_id="req_1",
            project_root=None,
        )
        result = sink.accept(None)
        assert isinstance(result, RejectedEvidence)
        assert result.reason == "missing-evidence"

# ---------------------------------------------------------------------------
# Exception isolation — sink never raises
# ---------------------------------------------------------------------------

class TestExceptionIsolation:
    """Sink catches all exceptions and returns RejectedEvidence."""

    def test_observer_exception_isolated(self):
        """When evidence triggers an exception during processing, sink returns RejectedEvidence."""
        # Create a mock evidence that passes initial checks but raises on
        # the timeline/event publish path (via project_root). We patch
        # _extract_scalar_allowlist to raise an exception.
        with patch(
            "audiagentic.components.agents.status.harness_status_evidence._extract_scalar_allowlist",
            side_effect=ValueError("corrupt data"),
        ):
            sink = StatusEvidenceSink(
                session_id="ses_test_1",
                request_id="req_1",
                project_root=MagicMock(),
            )
            evidence = _make_evidence(sequence=1)
            result = sink.accept(evidence)
            assert isinstance(result, RejectedEvidence)
            assert result.reason == "sink-exception"

    def test_timeline_failure_isolated(self):
        """Timeline append failure doesn't break accept — still returns AcceptedEvidence."""
        with patch(
            "audiagentic.components.agents.status.harness_status_evidence.session_store"
        ) as mock_store:
            mock_store.record_session_timeline.side_effect = Exception("IO error")
            sink = StatusEvidenceSink(
                session_id="ses_test_1",
                request_id="req_1",
                project_root=MagicMock(),
            )
            evidence = _make_evidence(sequence=1)
            result = sink.accept(evidence)
            assert isinstance(result, AcceptedEvidence)
            assert result.timeline_recorded is False

    def test_event_publish_failure_isolated(self):
        """Event publish failure doesn't break accept — still returns AcceptedEvidence."""
        with patch(
            "audiagentic.foundation.event.get_bus"
        ) as mock_get_bus:
            mock_get_bus.side_effect = Exception("bus error")
            sink = StatusEvidenceSink(
                session_id="ses_test_1",
                request_id="req_1",
                project_root=None,
            )
            evidence = _make_evidence(sequence=1)
            result = sink.accept(evidence)
            assert isinstance(result, AcceptedEvidence)
            assert result.event_published is False

# ---------------------------------------------------------------------------
# No Acp* import validation
# ---------------------------------------------------------------------------

class TestNoProviderNativeImport:
    """Verify the evidence sink module never imports any provider-native type."""

    def test_no_provider_native_import_in_module(self):
        """The agents_harness_status_evidence module contains no 'Acp' import references."""
        import audiagentic.components.agents.status.harness_status_evidence as mod
        source = open(mod.__file__).read()
        # Check that no line contains an import of a provider-native type.
        # The docstring may reference the rule but must not import it.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                assert "Acp" not in stripped, (
                    f"Evidence sink must never import provider-native types (AS19 validation rule): {stripped!r}"
                )
