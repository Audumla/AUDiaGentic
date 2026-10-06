"""AS49 — SessionRuntime.resume_session() end-to-end dispatch tests.

Unlike test_agents_gateway_session_resume.py (pure validate_resume_eligibility
unit tests), this exercises the real orchestration path: real AS29 surface
resolution against a registered fake descriptor, real session-store/binding
persistence, a fake provider_prepare_fn standing in for the real ACP
transport, and the idempotency record. Context fingerprints are supplied only
for the fake surface because it declares that same-context resume is required;
persistence-compatible surfaces such as GPT Auto intentionally ignore gateway
fingerprint drift.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.agents.gateway.session import bindings as binding_store
from audiagentic.components.agents.gateway.session import sessions_store as session_store
from audiagentic.components.agents.gateway.session.resume import (
    ERR_IDEMPOTENT_REPLAY_OF_FAILURE,
    ERR_SOURCE_NOT_TERMINAL,
    ERR_UNSUPPORTED_CAPABILITY,
    lookup_resume_attempt,
)
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)
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
        execution_profile_id="profile-1",
        provider_id=_PROVIDER_ID,
        model_id="m1",
        provider_session_ref="source-provider-ref-1",
        surface_id=_SURFACE_ID,
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
    def default_resume_prepare(
        project_root, *, provider_id, surface_hint, model_id=None, resume_provider_ref=None, **_ignored
    ):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = _ignored["ag_session_id"]
        if resume_provider_ref:
            transport.provider_session_ref = resume_provider_ref
        return _build_fake_prepared(transport)

    return SessionRuntime(
        clock=_Clock(), reap_interval_seconds=60,
        provider_prepare_fn=resume_prepare or default_resume_prepare,
    )


class TestResumeSuccess:
    def test_resume_preserves_provider_neutral_binding_identity(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)
        runtime = _make_runtime()
        try:
            resumed = runtime.resume_session(
                tmp_path,
                source["session-id"],
                control_id="ctrl-provider-neutral",
                execution_context_fingerprint=_EXECUTION_FP,
            )
            assert resumed["binding"]["provider-id"] == _PROVIDER_ID
            assert resumed["binding"]["surface-id"] == _SURFACE_ID
            assert resumed["binding"]["relation"] == "resumed-from"
            assert (
                resumed["binding"]["identity-context-fingerprint"]
                == source["binding"]["identity-context-fingerprint"]
            )
        finally:
            runtime.shutdown()

    def test_resume_creates_new_generation_linked_to_source(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)
        runtime = _make_runtime()
        try:
            new_record = runtime.resume_session(
                tmp_path,
                source["session-id"],
                control_id="ctrl-1",
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

    def test_observation_only_resume_defers_unresolved_reconciliation_before_open(
        self, tmp_path: Path
    ):
        source = _write_terminal_source_session(tmp_path)
        transports: list[FakeAgentSessionTransport] = []

        def prepare(
            project_root, *, provider_id, surface_hint, model_id=None,
            resume_provider_ref=None, **ignored
        ):
            transport = FakeAgentSessionTransport()
            transport.ag_session_id = ignored["ag_session_id"]
            transport.provider_session_ref = resume_provider_ref or "x"
            transports.append(transport)
            return _build_fake_prepared(transport)

        runtime = _make_runtime(resume_prepare=prepare)
        try:
            resumed = runtime.resume_session(
                tmp_path,
                source["session-id"],
                control_id="ctrl-observation-only",
                execution_context_fingerprint=_EXECUTION_FP,
                resume_existing=True,
            )
            assert resumed["session-id"] != source["session-id"]
            assert transports[0].defer_unresolved_calls == 1
        finally:
            runtime.shutdown()

    def test_resume_buffers_provider_binding_update_until_successor_exists(
        self, tmp_path: Path
    ):
        source = _write_terminal_source_session(tmp_path)
        session_store.update_provider_metadata(
            tmp_path,
            source["session-id"],
            {
                "chat-url": "https://chatgpt.com/g/g-p-project/c/source-provider-ref-1",
                "provider-session-id": "source-provider-ref-1",
                "project-url": "https://chatgpt.com/g/g-p-project/project",
            },
        )
        prepared_hints: list[dict[str, Any]] = []

        def prepare(
            project_root, *, provider_id, surface_hint, model_id=None,
            resume_provider_ref=None, **ignored
        ):
            binding_sink = ignored["binding_sink"]
            prepared_hints.append(dict(ignored["resume_provider_metadata"]))

            class PublishingTransport(FakeAgentSessionTransport):
                async def open(self):
                    await binding_sink(
                        ProviderSessionBindingUpdate(
                            provider_session_ref=ProviderSessionRef(
                                value=resume_provider_ref
                            ),
                            metadata={
                                "chat-url": prepared_hints[-1]["chat-url"],
                                "target-id": "target-rebound",
                            },
                        )
                    )
                    return await super().open()

            transport = PublishingTransport()
            transport.ag_session_id = ignored["ag_session_id"]
            transport.provider_session_ref = resume_provider_ref or "x"
            return _build_fake_prepared(transport)

        runtime = _make_runtime(resume_prepare=prepare)
        try:
            resumed = runtime.resume_session(
                tmp_path,
                source["session-id"],
                control_id="ctrl-binding-before-successor",
                execution_context_fingerprint=_EXECUTION_FP,
            )
        finally:
            runtime.shutdown()

        assert prepared_hints[0]["chat-url"].endswith("/source-provider-ref-1")
        assert resumed["provider"]["metadata"]["target-id"] == "target-rebound"
        assert resumed["binding"]["provider-session-ref"] == "source-provider-ref-1"
    def test_resume_rehydrates_canonical_active_provider_owner_before_persistence(
        self, tmp_path: Path
    ):
        source = _write_terminal_source_session(tmp_path)
        active = session_store.build_session_record(
            execution_profile_id=source["execution-profile-id"],
            provider_id=_PROVIDER_ID,
            model_id="m1",
            provider_session_ref="source-provider-ref-1",
            surface_id=_SURFACE_ID,
            idle_timeout_seconds=900,
            max_lifetime_seconds=14_400,
            provider_metadata={"chat-url": "https://chatgpt.com/g/g-p-project/c/source-provider-ref-1"},
        )
        active["binding"] = binding_store.resume_binding(
            session_id=active["session-id"],
            provider_id=_PROVIDER_ID,
            surface_id=_SURFACE_ID,
            provider_ref="source-provider-ref-1",
            predecessor_binding_id="different-intermediate-generation",
            ref_namespace=source["binding"].get("ref-namespace"),
            identity_context_fingerprint=source["binding"].get(
                "identity-context-fingerprint"
            ),
            execution_context_fingerprint=source["binding"].get(
                "execution-context-fingerprint"
            ),
        )
        session_store.write_session_record(tmp_path, active)
        binding_store.register_open_binding(tmp_path, active)

        runtime = _make_runtime()
        try:
            resumed = runtime.resume_session(
                tmp_path,
                source["session-id"],
                control_id="ctrl-canonical-active-owner",
                execution_context_fingerprint=_EXECUTION_FP,
            )
            persisted = session_store.read_session_record(
                tmp_path, active["session-id"]
            )
        finally:
            runtime.shutdown()

        assert resumed["session-id"] == active["session-id"]
        assert resumed["state"] == "active"
        assert resumed["binding"]["binding-id"] == active["binding"]["binding-id"]
        assert persisted["state"] == "active"
    def test_idempotent_replay_returns_same_new_session(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)
        call_count = 0

        def counting_prepare(
            project_root, *, provider_id, surface_hint, model_id=None, resume_provider_ref=None, **_ignored
        ):
            nonlocal call_count
            call_count += 1
            transport = FakeAgentSessionTransport()
            transport.ag_session_id = _ignored["ag_session_id"]
            transport.provider_session_ref = resume_provider_ref or "x"
            return _build_fake_prepared(transport)

        runtime = _make_runtime(resume_prepare=counting_prepare)
        try:
            first = runtime.resume_session(
                tmp_path, source["session-id"], control_id="ctrl-replay",
                execution_context_fingerprint=_EXECUTION_FP,
            )
            second = runtime.resume_session(
                tmp_path, source["session-id"], control_id="ctrl-replay",
                execution_context_fingerprint=_EXECUTION_FP,
            )
            assert first["session-id"] == second["session-id"]
            # Provider was only ever dispatched once — the replay never
            # re-opened a second real provider session.
            assert call_count == 1
        finally:
            runtime.shutdown()

    def test_resume_persistence_failure_terminalizes_provisional_successor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        source = _write_terminal_source_session(tmp_path)

        def fail_register(*_args, **_kwargs):
            raise AudiaGenticError(
                code="CON-AGW-096",
                kind="agents",
                message="duplicate owned provider session binding",
                details={},
            )

        monkeypatch.setattr(binding_store, "register_open_binding", fail_register)
        runtime = _make_runtime()
        try:
            with pytest.raises(AudiaGenticError) as exc:
                runtime.resume_session(
                    tmp_path,
                    source["session-id"],
                    control_id="ctrl-persistence-failure-rolls-back",
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert exc.value.code == "IO-AGW-119"
            records = session_store.list_session_records(tmp_path)
            successors = [
                item
                for item in records
                if item["session-id"] != source["session-id"]
            ]
            assert successors
            assert all(item["state"] == "failed" for item in successors)
            assert runtime.live_session_ids() == []
        finally:
            runtime.shutdown()
    def test_resume_rehydrates_existing_successor_after_prior_persistence_failure(
        self, tmp_path: Path
    ):
        source = _write_terminal_source_session(tmp_path)
        existing = session_store.build_session_record(
            execution_profile_id=source["execution-profile-id"],
            provider_id=_PROVIDER_ID,
            model_id="m1",
            provider_session_ref="source-provider-ref-1",
            surface_id=_SURFACE_ID,
            idle_timeout_seconds=900,
            max_lifetime_seconds=14_400,
        )
        existing["binding"] = binding_store.resume_binding(
            session_id=existing["session-id"],
            provider_id=_PROVIDER_ID,
            surface_id=_SURFACE_ID,
            provider_ref="source-provider-ref-1",
            predecessor_binding_id=source["binding"]["binding-id"],
            ref_namespace=source["binding"].get("ref-namespace"),
            identity_context_fingerprint=_IDENTITY_FP,
            execution_context_fingerprint=_EXECUTION_FP,
        )
        session_store.write_session_record(tmp_path, existing)
        binding_store.register_open_binding(tmp_path, existing)

        runtime = _make_runtime()
        try:
            resumed = runtime.resume_session(
                tmp_path,
                source["session-id"],
                control_id="ctrl-rehydrate-existing-successor",
                execution_context_fingerprint=_EXECUTION_FP,
            )
            assert resumed["session-id"] == existing["session-id"]
            assert runtime.live_session_ids() == [existing["session-id"]]
        finally:
            runtime.shutdown()


    def test_resume_reconstructs_missing_binding_from_durable_provider_metadata(
        self, tmp_path: Path
    ):
        record = session_store.build_session_record(
            execution_profile_id="profile-1",
            provider_id=_PROVIDER_ID,
            model_id="m1",
            provider_session_ref=None,
            surface_id=_SURFACE_ID,
            idle_timeout_seconds=900,
            max_lifetime_seconds=14_400,
            provider_metadata={
                "chat-url": "https://chatgpt.com/g/g-p-project/c/source-provider-ref-1",
                "provider-session-id": "source-provider-ref-1",
                "surface-id": _SURFACE_ID,
                "ref-namespace": "provider-session-ref",
                "identity-context-fingerprint": _IDENTITY_FP,
                "execution-context-fingerprint": _EXECUTION_FP,
            },
        )
        session_store.write_session_record(tmp_path, record)
        closed = session_store.transition_session_record(
            tmp_path,
            record["session-id"],
            "failed",
            updates={"close-reason": "failed"},
        )
        # The provider metadata survived, but the initial binding never did.
        session_store.write_session_record(tmp_path, closed)

        runtime = _make_runtime()
        try:
            resumed = runtime.resume_session(
                tmp_path,
                closed["session-id"],
                control_id="ctrl-metadata-recovery",
                execution_context_fingerprint=_EXECUTION_FP,
            )
            assert resumed["binding"]["provider-session-ref"] == "source-provider-ref-1"
            assert resumed["binding"]["relation"] == "resumed-from"
        finally:
            runtime.shutdown()


class TestResumeRejections:
    @pytest.mark.parametrize("surface_id", ["acp", "mcp-a2a"])
    def test_provider_neutral_surface_resume_contract(self, tmp_path: Path, surface_id: str):
        source = _write_terminal_source_session(tmp_path)
        runtime = _make_runtime()
        try:
            resumed = runtime.resume_session(
                tmp_path, source["session-id"], control_id=f"ctrl-{surface_id}",
                execution_context_fingerprint=_EXECUTION_FP,
            )
            assert resumed["binding"]["relation"] == "resumed-from"
            assert resumed["binding"]["provider-id"] == _PROVIDER_ID
        finally:
            runtime.shutdown()

    def test_active_source_rejected(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path, state="active")
        # Undo the terminal transition/retirement above for this one test —
        # build a genuinely active source instead.
        runtime = _make_runtime()
        try:
            with pytest.raises(AudiaGenticError) as exc:
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-2",
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert exc.value.code == ERR_SOURCE_NOT_TERMINAL
        finally:
            runtime.shutdown()

    def test_unsupported_transport_rejected_no_live_session(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)

        def unsupported_prepare(
            project_root, *, provider_id, surface_hint, model_id=None, resume_provider_ref=None, **_ignored
        ):
            return PreparedSessionTransport(  # type: ignore[arg-type]
                transport=None,
                surface=None,  # type: ignore[arg-type]
                effective_provider_ref=None,  # type: ignore[arg-type]
            )

        runtime = _make_runtime(resume_prepare=unsupported_prepare)
        try:
            with pytest.raises(AudiaGenticError, match="CON-AGW-095"):
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-3",
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert runtime.live_session_ids() == []
        finally:
            runtime.shutdown()

    def test_returned_provider_ref_must_match_source(self, tmp_path: Path):
        source = _write_terminal_source_session(tmp_path)

        def mismatched_prepare(
            project_root, *, provider_id, surface_hint, model_id=None,
            resume_provider_ref=None, **_ignored
        ):
            transport = FakeAgentSessionTransport()
            transport.ag_session_id = _ignored["ag_session_id"]
            transport.provider_session_ref = "different-provider-ref"
            return _build_fake_prepared(transport)

        runtime = _make_runtime(resume_prepare=mismatched_prepare)
        try:
            with pytest.raises(AudiaGenticError) as exc:
                runtime.resume_session(
                    tmp_path,
                    source["session-id"],
                    control_id="ctrl-ref-mismatch",
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert exc.value.code == "CON-AGW-123"
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
                    execution_context_fingerprint="wrong-fp",
                )
            entry = lookup_resume_attempt(tmp_path, source["session-id"], "ctrl-4")
            assert entry is not None
            assert entry["outcome"] == "failed"

            with pytest.raises(AudiaGenticError) as exc:
                runtime.resume_session(
                    tmp_path, source["session-id"], control_id="ctrl-4",
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
                    execution_context_fingerprint=_EXECUTION_FP,
                )
            assert exc.value.code == ERR_UNSUPPORTED_CAPABILITY
        finally:
            runtime.shutdown()
