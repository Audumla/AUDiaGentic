"""AS19 Stage-1 harness status observer foundation contract tests."""

from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.harness_status_observer import (
    StatusEvidence,
    StatusEvidenceSemanticStrength,
    StatusEvidenceSourceKind,
    StatusObserverLease,
    StatusObserverRequest,
    StatusObserverResult,
    StatusObserverState,
)


class TestStatusEvidence:
    """StatusEvidence frozen dataclass and validation."""

    def test_status_evidence_frozen(self):
        """StatusEvidence is immutable."""
        evidence = StatusEvidence(
            status="model-thinking",
            session_id="ses_1",
            request_id="req_1",
            correlation_id="corr_1",
            observed_at="2026-07-20T10:00:00Z",
            sequence=0,
            source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        )
        with pytest.raises(AttributeError):
            evidence.status = "model-waiting"  # type: ignore

    def test_status_evidence_rejects_empty_status(self):
        """Empty status is rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusEvidence(
                status="",
                session_id="ses_1",
                request_id="req_1",
                correlation_id="corr_1",
                observed_at="2026-07-20T10:00:00Z",
                sequence=0,
                source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
            )
        assert "status must be a non-empty string" in str(exc_info.value)

    def test_status_evidence_rejects_empty_session_id(self):
        """Empty session_id is rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusEvidence(
                status="model-thinking",
                session_id="",
                request_id="req_1",
                correlation_id="corr_1",
                observed_at="2026-07-20T10:00:00Z",
                sequence=0,
                source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
            )
        assert "session_id must be a non-empty string" in str(exc_info.value)

    def test_status_evidence_allows_none_request_id(self):
        """None request_id is allowed for session-level events."""
        evidence = StatusEvidence(
            status="session-opening",
            session_id="ses_1",
            request_id=None,
            correlation_id="corr_1",
            observed_at="2026-07-20T10:00:00Z",
            sequence=None,
            source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        )
        assert evidence.request_id is None

    def test_status_evidence_rejects_negative_sequence(self):
        """Negative sequence is rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusEvidence(
                status="model-thinking",
                session_id="ses_1",
                request_id="req_1",
                correlation_id="corr_1",
                observed_at="2026-07-20T10:00:00Z",
                sequence=-1,
                source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
            )
        assert "sequence must be a non-negative integer or None" in str(exc_info.value)

    def test_status_evidence_source_kind_enum(self):
        """StatusEvidenceSourceKind is closed."""
        evidence = StatusEvidence(
            status="model-thinking",
            session_id="ses_1",
            request_id="req_1",
            correlation_id="corr_1",
            observed_at="2026-07-20T10:00:00Z",
            sequence=0,
            source_kind=StatusEvidenceSourceKind.MANAGED_HOOK,
        )
        assert evidence.source_kind == "managed-hook"

    def test_status_evidence_semantic_strength_default(self):
        """Semantic strength defaults to 'unknown'."""
        evidence = StatusEvidence(
            status="model-thinking",
            session_id="ses_1",
            request_id="req_1",
            correlation_id="corr_1",
            observed_at="2026-07-20T10:00:00Z",
            sequence=0,
            source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        )
        assert evidence.semantic_strength == StatusEvidenceSemanticStrength.UNKNOWN


class TestStatusObserverRequest:
    """StatusObserverRequest validation."""

    def test_observer_request_frozen(self):
        """Request is immutable."""
        request = StatusObserverRequest(
            project_root="/path",
            provider_id="opencode",
            surface_id="opencode-acp",
            session_id="ses_1",
            request_id="req_1",
        )
        with pytest.raises(AttributeError):
            request.provider_id = "other"  # type: ignore

    def test_observer_request_rejects_empty_project_root(self):
        """Empty project_root is rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusObserverRequest(
                project_root="",
                provider_id="opencode",
                surface_id="opencode-acp",
                session_id="ses_1",
                request_id="req_1",
            )
        assert "project_root must be a non-empty string" in str(exc_info.value)

    def test_observer_request_with_accepted_statuses(self):
        """Accepted statuses can be provided."""
        request = StatusObserverRequest(
            project_root="/path",
            provider_id="opencode",
            surface_id="opencode-acp",
            session_id="ses_1",
            request_id="req_1",
            accepted_statuses=frozenset({"model-thinking", "tool-calling"}),
        )
        assert "model-thinking" in request.accepted_statuses


class TestStatusObserverResult:
    """StatusObserverResult validation."""

    def test_observer_result_ok_requires_supported(self):
        """ok=true requires supported=true."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusObserverResult(
                ok=True,
                supported=False,
                state=StatusObserverState.UNSUPPORTED,
            )
        assert "ok=true requires supported=true" in str(exc_info.value)

    def test_observer_result_ok_requires_binding_id(self):
        """ok=true requires binding_id."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusObserverResult(
                ok=True,
                supported=True,
                state=StatusObserverState.READY,
                binding_id=None,
            )
        assert "ok=true requires a non-None binding_id" in str(exc_info.value)

    def test_observer_result_unsupported(self):
        """Unsupported surface returns ok=false, supported=false."""
        result = StatusObserverResult(
            ok=False,
            supported=False,
            state=StatusObserverState.UNSUPPORTED,
            error_code="UNS-TRANSPORT-001",
        )
        assert result.ok is False
        assert result.supported is False
        assert result.state == StatusObserverState.UNSUPPORTED

    def test_observer_result_success(self):
        """Successful observer open."""
        result = StatusObserverResult(
            ok=True,
            supported=True,
            state=StatusObserverState.READY,
            binding_id="binding_1",
            launch_environment={"OBSERVER_TOKEN": "secret"},
            managed_ids=["hook_1", "plugin_1"],
        )
        assert result.ok is True
        assert result.binding_id == "binding_1"
        assert "hook_1" in result.managed_ids


class TestStatusObserverLease:
    """StatusObserverLease binding and operations."""

    def test_observer_lease_frozen(self):
        """Lease is immutable."""
        lease = StatusObserverLease(
            binding_id="binding_1",
            observe_transport=lambda obs: None,
        )
        with pytest.raises(AttributeError):
            lease.binding_id = "binding_2"  # type: ignore

    def test_observer_lease_rejects_empty_binding_id(self):
        """Empty binding_id is rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusObserverLease(
                binding_id="",
                observe_transport=lambda obs: None,
            )
        assert "binding_id must be a non-empty string" in str(exc_info.value)

    def test_observer_lease_rejects_non_callable_normalizer(self):
        """Non-callable observe_transport is rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            StatusObserverLease(
                binding_id="binding_1",
                observe_transport="not-callable",  # type: ignore
            )
        assert "observe_transport must be callable" in str(exc_info.value)

    def test_observer_lease_accepts_callable_normalizer(self):
        """Callable observe_transport is accepted."""
        def dummy_normalizer(obs):
            return None

        lease = StatusObserverLease(
            binding_id="binding_1",
            observe_transport=dummy_normalizer,
        )
        assert lease.observe_transport == dummy_normalizer
