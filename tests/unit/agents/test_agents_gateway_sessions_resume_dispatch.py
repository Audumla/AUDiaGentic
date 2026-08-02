"""AS49 — SessionRuntime.resume_session() end-to-end dispatch tests.

Unlike test_agents_gateway_session_resume.py (pure validate_resume_eligibility
unit tests), this exercises the real orchestration path: real AS29 surface
resolution against a registered fake descriptor, real session-store/binding
persistence, a fake provider_prepare_fn standing in for the real ACP
transport, and the idempotency record.

Real production sessions opened via SessionRuntime.open_session() today never
carry real identity/execution-context fingerprints (build_session_record's
binding always defaults both to "unknown" — no open_session call site plumbs
real SH02 fingerprints through yet). Since validate_resume_eligibility
unconditionally rejects the "unknown" sentinel, no session opened through the
current gateway open path can actually be resumed yet. That's a real,
separate gap (SH02/AS08 territory, not AS49's own scope) — worth flagging,
not silently worked around. This test file constructs its source session's
binding directly with real fingerprints to exercise resume in isolation from
that gap.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.agents import agents_gateway_session_bindings as binding_store
from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_gateway_session_resume import (
    ERR_IDEMPOTENT_REPLAY_OF_FAILURE,
    ERR_SOURCE_NOT_TERMINAL,
    ERR_UNSUPPORTED_CAPABILITY,
    lookup_resume_attempt,
)
from audiagentic.components.agents.agents_gateway_sessions import SessionRuntime
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import PreparedSessionTransport

from .test_agents_gateway_sessions import FakeAgentSessionTransport, _build_fake_prepared

_PROVIDER_ID = "test-resume-provider"
_SURFACE_ID = "test-resume-acp"
_IDENTITY_FP = "id-fp-real-001"
_EXECUTION_FP = "exec-fp-real-001"


def _register_resumable_descriptor() -> None:
    from audiagentic.components.providers.descriptors.base import ProviderDescriptor
    from audiagentic.components.providers.descriptors.registry import register
    from audiagentic.components.providers.descriptors.session_surface_declarations import (
        SessionSurfaceDeclaration,
    )
    from audiagentic.foundation.transports.session_surface import (
        ControlSupport,
        SessionIdentityOperation,
        SessionMappingFacts,
        ValidationEvidence,
    )

    decl = SessionSurfaceDeclaration(
        surface_id=_SURFACE_ID,
        version_constraint=">=1.0",
        identity_operations={
            SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
            SessionIdentityOperation.RESUME_BY_REF: ControlSupport.SUPPORTED,
        },
        mapping_facts=SessionMappingFacts(ref_namespace="provider-session-ref"),
        evidence=ValidationEvidence(validated=True, reference="test"),
    )
    register(
        ProviderDescriptor(
            provider_id=_PROVIDER_ID,
            display_name=_PROVIDER_ID,
            execution_isolation_tier="no-isolation",
            session_surfaces=(decl,),
        )
    )


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path: Path):
    from audiagentic.components.providers.descriptors.registry import _registry
    from audiagentic.components.providers.services.config.provider_config import (
        set_provider_enabled,
    )

    _registry._items.clear()
    _register_resumable_descriptor()
    set_provider_enabled(tmp_path, _PROVIDER_ID, enabled=True)
    yield


def _write_terminal_source_session(
    project_root: Path, *, state: str = "closed",
) -> dict[str, Any]:
    """Build+persist a source session record with a REAL (non-'unknown')
    binding, already terminal — the shape resume_session requires."""
    record = session_store.build_session_record(
        agent_profile_id="profile-1",
        provider_id=_PROVIDER_ID,
        model_id="m1",
        provider_session_ref="source-provider-ref-1",
        idle_timeout_seconds=900,
        max_lifetime_seconds=14_400,
    )
    record["binding"] = binding_store.build_binding(
        provider_id=_PROVIDER_ID,
        provider_session_ref="source-provider-ref-1",
        surface_id=_SURFACE_ID,
        ref_namespace="provider-session-ref",
        identity_context_fingerprint=_IDENTITY_FP,
        execution_context_fingerprint=_EXECUTION_FP,
    )
    session_store.write_session_record(project_root, record)
    binding_store.register_open_binding(project_root, record)
    if state == "active":
        return record  # build_session_record already starts "active"
    updated = session_store.transition_session_record(
        project_root, record["session-id"], state,
        updates={"close-reason": "client-request"},
    )
    binding_store.retire_binding(project_root, updated, state=state)
    return updated


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _make_runtime(*, resume_prepare=None) -> SessionRuntime:
    def default_resume_prepare(project_root, *, provider_id, surface_hint, model_id=None, resume_provider_ref=None):
        transport = FakeAgentSessionTransport()
        if resume_provider_ref:
            transport.provider_session_ref = resume_provider_ref
        return _build_fake_prepared(transport)

    return SessionRuntime(
        clock=_Clock(), reap_interval_seconds=60,
        provider_prepare_fn=resume_prepare or default_resume_prepare,
    )


class TestResumeSuccess:
    def test_resume_creates_new_generation_linked_to_source(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)
        runtime = _make_runtime()
        try:
            new_record = runtime.resume_session(
                tmp_path,
                source["session-id"],
                control_id="ctrl-1",
                identity_context_fingerprint=_IDENTITY_FP,
                execution_context_fingerprint=_EXECUTION_FP,
                model_id="m1",
            )
            assert new_record["session-id"] != source["session-id"]
            assert new_record["state"] == "active"
            assert new_record["binding"]["relation"] == "resumed-from"
            assert new_record["binding"]["predecessor-binding-id"] == source["binding"]["binding-id"]
            # Source itself remains untouched/terminal.
            reread_source = session_store.read_session_record(tmp_path, source["session-id"])
            assert reread_source["state"] == "closed"
            assert runtime.live_session_ids() == [new_record["session-id"]]
        finally:
            runtime.shutdown()

    def test_idempotent_replay_returns_same_new_session(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)
        call_count = 0

        def counting_prepare(project_root, *, provider_id, surface_hint, model_id=None, resume_provider_ref=None):
            nonlocal call_count
            call_count += 1
            transport = FakeAgentSessionTransport()
            transport.provider_session_ref = resume_provider_ref or "x"
            return _build_fake_prepared(transport)

        runtime = _make_runtime(resume_prepare=counting_prepare)
        try:
            first = runtime.resume_session(
                tmp_path, source["session-id"], control_id="ctrl-replay",
                identity_context_fingerprint=_IDENTITY_FP,
                execution_context_fingerprint=_EXECUTION_FP,
            )
            second = runtime.resume_session(
                tmp_path, source["session-id"], control_id="ctrl-replay",
                identity_context_fingerprint=_IDENTITY_FP,
                execution_context_fingerprint=_EXECUTION_FP,
            )
            assert first["session-id"] == second["session-id"]
            # Provider was only ever dispatched once — the replay never
            # re-opened a second real provider session.
            assert call_count == 1
        finally:
            runtime.shutdown()


class TestResumeRejections:
    def test_active_source_rejected(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path, state="active")
        # Undo the terminal transition/retirement above for this one test —
        # build a genuinely active source instead.
        runtime = _make_runtime()
        try:
            with pytest.raises(AudiaGenticError) as exc:
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-2",
                    identity_context_fingerprint=_IDENTITY_FP,
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert exc.value.code == ERR_SOURCE_NOT_TERMINAL
        finally:
            runtime.shutdown()

    def test_unsupported_transport_rejected_no_live_session(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)

        def unsupported_prepare(project_root, *, provider_id, surface_hint, model_id=None, resume_provider_ref=None):
            return PreparedSessionTransport(transport=None, surface=None, effective_provider_ref=None)

        runtime = _make_runtime(resume_prepare=unsupported_prepare)
        try:
            with pytest.raises(AudiaGenticError, match="CON-AGW-095"):
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-3",
                    identity_context_fingerprint=_IDENTITY_FP,
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert runtime.live_session_ids() == []
        finally:
            runtime.shutdown()

    def test_failed_attempt_recorded_and_replay_raises_conflict(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)
        runtime = _make_runtime()
        try:
            with pytest.raises(AudiaGenticError):
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-4",
                    identity_context_fingerprint="wrong-fp",
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            entry = lookup_resume_attempt(tmp_path, source["session-id"], "ctrl-4")
            assert entry is not None
            assert entry["outcome"] == "failed"

            with pytest.raises(AudiaGenticError) as exc:
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-4",
                    identity_context_fingerprint=_IDENTITY_FP,
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert exc.value.code == ERR_IDEMPOTENT_REPLAY_OF_FAILURE
        finally:
            runtime.shutdown()

    def test_unknown_capability_surface_rejected(self, tmp_path: Path):
        """A surface that doesn't declare resume-by-ref: supported is rejected
        (real AS29 resolver path, not the injected transport fake)."""
        from audiagentic.components.providers.descriptors.base import ProviderDescriptor
        from audiagentic.components.providers.descriptors.registry import _registry, register
        from audiagentic.components.providers.descriptors.session_surface_declarations import (
            SessionSurfaceDeclaration,
        )
        from audiagentic.components.providers.services.config.provider_config import (
            set_provider_enabled,
        )
        from audiagentic.foundation.transports.session_surface import (
            ControlSupport,
            SessionIdentityOperation,
        )

        _registry._items.clear()
        register(
            ProviderDescriptor(
                provider_id=_PROVIDER_ID,
                display_name=_PROVIDER_ID,
                execution_isolation_tier="no-isolation",
                session_surfaces=(
                    SessionSurfaceDeclaration(
                        surface_id=_SURFACE_ID,
                        version_constraint=">=1.0",
                        identity_operations={
                            SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
                            SessionIdentityOperation.RESUME_BY_REF: ControlSupport.UNSUPPORTED,
                        },
                    ),
                ),
            )
        )
        set_provider_enabled(tmp_path, _PROVIDER_ID, enabled=True)

        source = _write_terminal_source_session(tmp_path)
        runtime = _make_runtime()
        try:
            with pytest.raises(AudiaGenticError) as exc:
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-5",
                    identity_context_fingerprint=_IDENTITY_FP,
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert exc.value.code == ERR_UNSUPPORTED_CAPABILITY
        finally:
            runtime.shutdown()
