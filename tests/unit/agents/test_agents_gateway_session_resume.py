"""AS49 — explicit resume eligibility checks and idempotency record.

Covers every distinct rejection reason in validate_resume_eligibility (never
a generic catch-all), plus the idempotency read/write round-trip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.session.resume import (
    ERR_EXECUTION_CONTEXT_MISMATCH,
    ERR_SOURCE_NOT_TERMINAL,
    ERR_STALE_OR_MISSING_BINDING,
    ERR_UNSUPPORTED_CAPABILITY,
    ERR_UNVALIDATED_SURFACE,
    ERR_VERSION_OR_REF_INCOMPATIBLE,
    lookup_resume_attempt,
    record_resume_attempt,
    validate_resume_eligibility,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    ControlSupport,
    ResolvedSessionSurface,
    SessionIdentityCapabilities,
    SessionIdentityOperation,
    SessionMappingFacts,
    SessionSurfaceRef,
    SurfaceValidation,
    ValidationEvidence,
)

_SOURCE_SESSION_ID = "ses_source0000000"


def _surface(
    *,
    surface_id: str = "pi-community-acp",
    resume_supported: bool = True,
    validated: bool = True,
    ref_namespace: str = "provider-session-ref",
    requires_same_execution_context: bool = True,
) -> ResolvedSessionSurface:
    identity_operations = {
        SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
        SessionIdentityOperation.RESUME_BY_REF: (
            ControlSupport.SUPPORTED if resume_supported else ControlSupport.UNSUPPORTED
        ),
    }
    return ResolvedSessionSurface(
        ref=SessionSurfaceRef(provider_id="pi", surface_id=surface_id, resolved_version="0.82.1"),
        identity=SessionIdentityCapabilities(
            identity_operations=identity_operations,
            mapping_facts=SessionMappingFacts(
                ref_namespace=ref_namespace,
                requires_same_project=True,
                requires_same_execution_context=requires_same_execution_context,
            ),
        ),
        validation=SurfaceValidation(
            evidence=ValidationEvidence(
                validated=validated, reference="test" if validated else "",
            ),
        ),
    )


def _binding(**overrides) -> dict:
    base = {
        "binding-id": "sbind_source0000",
        "provider-id": "pi",
        "surface-id": "pi-community-acp",
        "ref-namespace": "provider-session-ref",
        "provider-session-ref": "provider-ref-xyz",
        "identity-context-fingerprint": "id-fp-abc",
        "execution-context-fingerprint": "exec-fp-abc",
    }
    base.update(overrides)
    return base


class TestSourceNotTerminal:
    def test_active_source_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="active",
                source_binding=_binding(),
                surface=_surface(),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_SOURCE_NOT_TERMINAL

    def test_closed_source_accepted_past_this_check(self):
        # closed + everything else matching should not raise this specific error
        validate_resume_eligibility(
            source_session_id=_SOURCE_SESSION_ID,
            source_state="closed",
            source_binding=_binding(),
            surface=_surface(),
            identity_context_fingerprint="id-fp-abc",
            execution_context_fingerprint="exec-fp-abc",
        )


class TestStaleOrMissingBinding:
    def test_none_binding_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=None,
                surface=_surface(),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_STALE_OR_MISSING_BINDING

    def test_binding_without_provider_ref_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(**{"provider-session-ref": None}),
                surface=_surface(),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_STALE_OR_MISSING_BINDING


class TestUnsupportedCapability:
    def test_resume_by_ref_unsupported_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(),
                surface=_surface(resume_supported=False),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_UNSUPPORTED_CAPABILITY


class TestUnvalidatedSurfaceGap:
    """The gap found in review: resume-by-ref: supported with an unvalidated
    surface must still be rejected — identity_operations alone is not proof."""

    def test_resume_by_ref_supported_but_unvalidated_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(),
                surface=_surface(resume_supported=True, validated=False),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_UNVALIDATED_SURFACE


class TestVersionOrRefIncompatible:
    def test_surface_id_mismatch_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(**{"surface-id": "pi-rpc"}),
                surface=_surface(surface_id="pi-community-acp"),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_VERSION_OR_REF_INCOMPATIBLE

    def test_ref_namespace_mismatch_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(**{"ref-namespace": "other-namespace"}),
                surface=_surface(ref_namespace="provider-session-ref"),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_VERSION_OR_REF_INCOMPATIBLE


class TestIdentityContextMismatch:
    def test_identity_fingerprint_is_not_required_for_provider_ref_resume(self):
        validate_resume_eligibility(
            source_session_id=_SOURCE_SESSION_ID,
            source_state="closed",
            source_binding=_binding(**{"identity-context-fingerprint": "unknown"}),
            surface=_surface(requires_same_execution_context=False),
            identity_context_fingerprint=None,
            execution_context_fingerprint=None,
        )


class TestExecutionContextMismatch:
    def test_missing_execution_fingerprint_rejected_when_required(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(),
                surface=_surface(requires_same_execution_context=True),
                execution_context_fingerprint=None,
            )
        assert exc.value.code == ERR_EXECUTION_CONTEXT_MISMATCH

    def test_mismatched_execution_fingerprint_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(),
                surface=_surface(),
                identity_context_fingerprint="id-fp-abc",
                execution_context_fingerprint="wrong-fp",
            )
        assert exc.value.code == ERR_EXECUTION_CONTEXT_MISMATCH

    def test_unknown_stored_fingerprint_rejected_when_required(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(**{"execution-context-fingerprint": "unknown"}),
                surface=_surface(requires_same_execution_context=True),
                execution_context_fingerprint="unknown",
            )
        assert exc.value.code == ERR_EXECUTION_CONTEXT_MISMATCH

    def test_persistence_compatible_surface_ignores_context_drift(self):
        validate_resume_eligibility(
            source_session_id=_SOURCE_SESSION_ID,
            source_state="closed",
            source_binding=_binding(**{"execution-context-fingerprint": "old-fp"}),
            surface=_surface(requires_same_execution_context=False),
            execution_context_fingerprint="new-fp",
        )

    def test_provider_id_mismatch_rejected(self):
        with pytest.raises(AudiaGenticError) as exc:
            validate_resume_eligibility(
                source_session_id=_SOURCE_SESSION_ID,
                source_state="closed",
                source_binding=_binding(**{"provider-id": "other-provider"}),
                surface=_surface(),
                execution_context_fingerprint="exec-fp-abc",
            )
        assert exc.value.code == ERR_VERSION_OR_REF_INCOMPATIBLE


class TestFullyEligible:
    def test_all_checks_pass_returns_binding(self):
        binding = _binding()
        result = validate_resume_eligibility(
            source_session_id=_SOURCE_SESSION_ID,
            source_state="closed",
            source_binding=binding,
            surface=_surface(),
            identity_context_fingerprint="id-fp-abc",
            execution_context_fingerprint="exec-fp-abc",
        )
        assert result is binding


class TestIdempotencyRoundTrip:
    def test_lookup_before_record_returns_none(self, tmp_path: Path):
        assert lookup_resume_attempt(tmp_path, _SOURCE_SESSION_ID, "ctrl-1") is None

    def test_record_then_lookup_succeeded(self, tmp_path: Path):
        record_resume_attempt(
            tmp_path, _SOURCE_SESSION_ID, "ctrl-1",
            outcome="succeeded", new_session_id="ses_new0000000000",
        )
        entry = lookup_resume_attempt(tmp_path, _SOURCE_SESSION_ID, "ctrl-1")
        assert entry is not None
        assert entry["outcome"] == "succeeded"
        assert entry["new-session-id"] == "ses_new0000000000"

    def test_record_then_lookup_failed(self, tmp_path: Path):
        record_resume_attempt(
            tmp_path, _SOURCE_SESSION_ID, "ctrl-2",
            outcome="failed", error_code=ERR_SOURCE_NOT_TERMINAL, error_message="not terminal",
        )
        entry = lookup_resume_attempt(tmp_path, _SOURCE_SESSION_ID, "ctrl-2")
        assert entry is not None
        assert entry["outcome"] == "failed"
        assert entry["error-code"] == ERR_SOURCE_NOT_TERMINAL

    def test_different_control_ids_do_not_collide(self, tmp_path: Path):
        record_resume_attempt(tmp_path, _SOURCE_SESSION_ID, "ctrl-a", outcome="succeeded", new_session_id="ses_a")
        record_resume_attempt(tmp_path, _SOURCE_SESSION_ID, "ctrl-b", outcome="succeeded", new_session_id="ses_b")
        assert lookup_resume_attempt(tmp_path, _SOURCE_SESSION_ID, "ctrl-a")["new-session-id"] == "ses_a"
        assert lookup_resume_attempt(tmp_path, _SOURCE_SESSION_ID, "ctrl-b")["new-session-id"] == "ses_b"

    def test_different_source_sessions_do_not_collide(self, tmp_path: Path):
        record_resume_attempt(tmp_path, "ses_source_one", "ctrl-x", outcome="succeeded", new_session_id="ses_1")
        record_resume_attempt(tmp_path, "ses_source_two", "ctrl-x", outcome="succeeded", new_session_id="ses_2")
        assert lookup_resume_attempt(tmp_path, "ses_source_one", "ctrl-x")["new-session-id"] == "ses_1"
        assert lookup_resume_attempt(tmp_path, "ses_source_two", "ctrl-x")["new-session-id"] == "ses_2"
