"""AS04 — sessionful dispatch routing tests (plan agent-sessions).

Real SessionRuntime + fake transport; provider/profile seams monkeypatched.
Pins: keep-alive opens and completes, session-id continues on the SAME live
transport, unsupported provider is terminal UNS-AGW-001, profile mismatch is
terminal VAL-AGW-060, and the one-shot path is untouched for plain records.

AS28 slice 4a: injects PreparedSessionTransport via provider_prepare_fn —
no AcpLaunch/AcpSessionTransport in the open path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.unit.agents.test_agents_gateway_sessions import (
    FakeAgentSessionTransport,
    _build_fake_prepared,
    _Clock,
)

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import dispatch as dispatch
from audiagentic.components.agents.gateway.session import dispatch as session_dispatch
from audiagentic.components.agents.gateway.session import sessions as sessions_module
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime

PROFILE = {
    "profile_id": "profile-1",
    "provider_id": "opencode",
    "instances": ["m1"],
    "model_alias": None,
    "surface_id": "test-surface",
    "params": {},
}

# GP13: the real "opencode" descriptor used by PROFILE above does not
# declare RESUME_BY_REF support, so auto-resume tests need their own
# resumable descriptor -- same pattern as
# test_agents_gateway_sessions_resume_dispatch.py's _register_resumable_descriptor.
# Surface id is pinned to "opencode-acp" because _build_fake_prepared (this
# rig's fake provider_prepare_fn helper, shared with test_agents_gateway_
# sessions.py) always echoes that exact surface id back regardless of the
# SurfaceHint it was given -- only the provider id actually reflects what
# was requested, so the registered descriptor's surface id must match the
# fake's hardcoded echo for resolve_session_surface to find it.
_RESUMABLE_PROVIDER_ID = "test-gp13-resumable-provider"
_RESUMABLE_SURFACE_ID = "opencode-acp"
_RESUMABLE_PROFILE = dict(PROFILE, provider_id=_RESUMABLE_PROVIDER_ID, surface_id=_RESUMABLE_SURFACE_ID)


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
        surface_id=_RESUMABLE_SURFACE_ID,
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
            provider_id=_RESUMABLE_PROVIDER_ID,
            display_name=_RESUMABLE_PROVIDER_ID,
            execution_isolation_tier="no-isolation",
            session_surfaces=(decl,),
        )
    )


@pytest.fixture
def resumable_rig(rig, monkeypatch):
    """GP13 auto-resume tests: same rig, but resolved against a provider
    whose registered descriptor actually declares resume-by-ref support."""
    import audiagentic.components.agents.configuration.global_catalog as agents_catalog
    from audiagentic.components.providers.descriptors.registry import _registry
    from audiagentic.components.providers.services.config.provider_config import (
        set_provider_enabled,
    )

    runtime, transports, tmp_path = rig
    _registry._items.clear()
    _register_resumable_descriptor()
    set_provider_enabled(tmp_path, _RESUMABLE_PROVIDER_ID, enabled=True)
    monkeypatch.setattr(agents_catalog, "resolve_global_execution_profile", lambda root, pid: dict(_RESUMABLE_PROFILE))
    yield runtime, transports, tmp_path


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=fake_prepare,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    import audiagentic.components.agents.configuration.global_catalog as agents_catalog

    monkeypatch.setattr(agents_catalog, "resolve_global_execution_profile", lambda root, pid: dict(PROFILE))
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.get_provider_runtime_config_state",
        lambda root, provider_id: {
            "provider-id": provider_id,
            "enabled": True,
            "config": {},
        },
    )
    yield runtime, transports, tmp_path
    runtime.shutdown()


def _running_record(tmp_path, **kwargs):
    # AS105/AS101: dispatch.py reads the bound model from resolved-model-id,
    # normally injected by queue.py's _run_one at dispatch time. Tests here
    # call dispatch.dispatch_request directly, bypassing the queue.
    kwargs.setdefault("resolved_model_id", "m1")
    record = store.build_record(execution_profile_id="profile-1", prompt_body="hello", **kwargs)
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-test", expected_revision=0
    )
    return store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-test",
        worker_id="worker_test",
        expected_revision=claimed["revision"],
    )


def _dispatch(
    tmp_path,
    record,
    *,
    dispatch_prompt,
    preallocated_session_id=None,
    provider_isolation_tier="full-isolation",
    context_fingerprint="0" * 64,
):
    return dispatch.dispatch_request(
        tmp_path,
        record,
        dispatch_prompt=dispatch_prompt,
        preallocated_session_id=preallocated_session_id,
        manifest_id="mf_test",
        context_fingerprint=context_fingerprint,
        component_profile="",
        provider_isolation_tier=provider_isolation_tier,
        worker_timeout_seconds=10,
    )


def test_keep_alive_opens_session_and_completes(rig):
    runtime, transports, tmp_path = rig
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="do the thing")
    assert result["state"] == "completed"
    assert result["session-id"] is not None
    assert result["provider-id"] == "opencode"
    assert result["completion"]["binding"]["provider-ref-key-prefix"]
    assert "provider-session-ref" not in repr(result["completion"])
    assert len(transports) == 1
    # SH02 keeps prompt bodies out of persisted records; dispatch receives the
    # raw prompt through its in-memory argument instead.
    assert transports[0].turns == ["do the thing"]
    assert not transports[0].closed  # keep-alive: session survives the request
    request_dir = (
        tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / record["request-id"]
    )
    assert (request_dir / "runtime").is_dir()


def test_preallocated_session_id_opens_new_session(rig):
    runtime, transports, tmp_path = rig
    preallocated = "ses_preallocated"
    record = _running_record(tmp_path, session_id=preallocated, session_keep_alive=True)
    result = _dispatch(
        tmp_path,
        record,
        dispatch_prompt="hello",
        preallocated_session_id=preallocated,
    )
    assert result["state"] == "completed"
    assert result["session-id"] == preallocated
    assert len(transports) == 1


def test_session_id_continues_same_live_transport(rig):
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="hello"
    )
    assert second["state"] == "completed"
    assert second["session-id"] == session_id
    assert len(transports) == 1  # no second child spawned
    assert transports[0].turns == ["hello", "hello"]


def test_persistent_surface_ignores_execution_context_drift_on_continuation(
    rig, monkeypatch
):
    """Persistent provider conversations survive a gateway context change.

    The request manifest fingerprint changes across a gateway restart/config
    reload.  A surface that explicitly declares
    ``requires_same_execution_context=False`` must continue its durable
    provider conversation; strict surfaces keep the exact-match guard.
    """
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path,
        _running_record(tmp_path, session_keep_alive=True),
        dispatch_prompt="hello",
        context_fingerprint="0" * 64,
    )
    session_id = first["session-id"]

    from audiagentic.foundation.transports.session_surface import SessionMappingFacts

    surface = SimpleNamespace(
        identity=SimpleNamespace(
            mapping_facts=SessionMappingFacts(
                requires_same_execution_context=False,
            )
        )
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.resolve_session_surface",
        lambda *args, **kwargs: surface,
    )

    second = _dispatch(
        tmp_path,
        _running_record(tmp_path, session_id=session_id),
        dispatch_prompt="after restart",
        context_fingerprint="1" * 64,
    )
    assert second["state"] == "completed", second
    assert second["session-id"] == session_id
    assert transports[0].turns == ["hello", "after restart"]


def test_unsupported_provider_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig

    # AS28 slice 4a: unsupported surface path — provider_prepare_fn returns
    # PreparedSessionTransport with transport=None, which raises CON-AGW-095.
    def unsupported_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):

        return _build_fake_prepared(None)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime, "_provider_prepare_fn", unsupported_prepare)
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="hello")
    assert result["state"] == "failed"
    assert result["error"]["code"] == "CON-AGW-095"
    assert transports == []
    request_dir = (
        tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / record["request-id"]
    )
    assert (request_dir / "quarantine" / record["request-id"]).is_dir()


def test_profile_mismatch_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]

    import audiagentic.components.agents.configuration.global_catalog as agents_catalog

    other = dict(PROFILE, profile_id="profile-2")
    monkeypatch.setattr(agents_catalog, "resolve_global_execution_profile", lambda root, pid: other)
    record = store.build_record(
        execution_profile_id="profile-2", prompt_body="hi", session_id=session_id
    )
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-test", expected_revision=0
    )
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-test",
        worker_id="worker_test_mismatch",
        expected_revision=claimed["revision"],
    )
    result = _dispatch(tmp_path, running, dispatch_prompt="hi")
    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-AGW-060"
    assert transports[0].turns == ["hello"]  # mismatch never reached the agent


def test_unknown_session_terminal(rig):
    runtime, transports, tmp_path = rig
    result = _dispatch(
        tmp_path, _running_record(tmp_path, session_id="ses_nope"), dispatch_prompt="hi"
    )
    assert result["state"] == "failed"
    assert result["error"]["code"] == "RES-AGW-002"


def test_session_output_concatenates_stream_chunks():
    """AS28: final_summary carries bounded assistant-text fragments."""
    from types import SimpleNamespace

    # SessionTurnResult with final_summary containing concatenated text fragments
    result = SimpleNamespace(
        final_summary="TOKEN STORED.",
    )
    assert session_dispatch._session_output_from_result(result) == "TOKEN STORED."


def test_plain_record_does_not_touch_session_path(rig, monkeypatch):
    runtime, transports, tmp_path = rig

    def boom(*args, **kwargs):  # session runtime must not be consulted
        raise AssertionError("session path used for a plain record")

    monkeypatch.setattr(sessions_module, "get_session_runtime", boom)

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        lambda **kwargs: SimpleNamespace(
            result_data={"provider-id": "opencode", "model": "m1", "output": "ok"}
        ),
    )
    result = _dispatch(tmp_path, _running_record(tmp_path), dispatch_prompt="do the thing")
    assert result["state"] == "completed", result
    assert transports == []


def test_closed_by_shutdown_session_transparently_resumes(resumable_rig):
    """GP13 (scoped): a session closed specifically by a gateway shutdown
    (the exact shape a force gateway_restart() produces machine-wide) is
    transparently reattached on the next continuation instead of forcing
    RES-AGW-003 -- reproduced live 2026-08-17 when a force restart
    (loading unrelated fixes) collaterally closed a concurrent agent's
    session in a different project."""
    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="shutdown")

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "completed", second
    # AS49/AS30: resume always creates a new generation -- never aliases the
    # closed source id onto the successor.
    assert second["session-id"] != session_id
    assert len(transports) == 2
    assert transports[1].turns == ["are you there"]

    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    successor = session_store.read_session_record(tmp_path, second["session-id"])
    assert successor["binding"]["relation"] == "resumed-from"
    assert successor["binding"]["predecessor-binding-id"] is not None


def test_closed_by_non_shutdown_reason_still_raises_res_agw_003(rig):
    """A session closed for any reason OTHER than a gateway shutdown (client
    request, post-turn auto-close, etc.) must NOT be transparently resumed
    -- GP13's own notes are explicit that undoing an intentional close is
    much closer to a correctness bug than the restart problem being fixed."""
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="client-request")

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "RES-AGW-003"
    assert len(transports) == 1  # no successor transport was ever opened


def test_failed_session_never_auto_resumes(rig):
    """A genuinely failed session must still require the caller's own
    explicit session_resume -- GP13's core invariant: a real terminal
    failure is never silently papered over by a transparent resume."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    session_store.transition_session_record(
        tmp_path, session_id, "failed", updates={"close-reason": "failed"}
    )
    # transition_session_record only touches the durable record -- the
    # runtime's own live in-process handle registry is a separate thing
    # entirely (a real "failed" session usually loses its handle via the
    # same event that fails it). Drop it directly so
    # session_runtime_status(...).get("available") is False, exactly like
    # after a real crash/restart.
    runtime._handles.pop(session_id, None)

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "RES-AGW-003"
    assert len(transports) == 1


def test_auto_resume_expected_refusal_falls_back_to_res_agw_003(resumable_rig, monkeypatch):
    """An expected AS49 eligibility refusal (e.g. the resolved surface
    doesn't actually support resume-by-ref) must fall back to the ordinary
    RES-AGW-003 the caller already knows how to handle -- resume is a
    best-effort transparent upgrade, never a new, different failure mode."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="shutdown")

    def refuse(*args, **kwargs):
        raise AudiaGenticError(
            code="UNS-AGW-112",
            kind="agents",
            message="resolved session surface does not support resume-by-ref",
            details={},
        )

    monkeypatch.setattr(runtime, "resume_session", refuse)

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "RES-AGW-003"


def test_auto_resume_unexpected_error_propagates_as_itself(resumable_rig, monkeypatch):
    """An error OUTSIDE AS49's known eligibility-refusal taxonomy (a store
    failure, a lost ownership fence, an internal resume defect) must never
    be masked as mere ineligibility -- it has to surface as itself so a
    real bug is never hidden behind an innocuous 'session isn't active'.
    CON-AGW-002 ("session runtime has been shut down") is a real,
    registered error code that is deliberately NOT in
    _AUTO_RESUME_EXPECTED_REFUSAL_CODES -- it stands in for any internal
    resume failure outside AS49's own eligibility taxonomy."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="shutdown")

    def explode(*args, **kwargs):
        raise AudiaGenticError(
            code="CON-AGW-002",
            kind="agents",
            message="session runtime has been shut down",
            details={},
        )

    monkeypatch.setattr(runtime, "resume_session", explode)

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "CON-AGW-002"


def test_no_isolation_plain_record_routes_through_ephemeral_session(rig, monkeypatch):
    """SH23: a no-isolation provider has no disposable-subprocess-per-attempt
    story (e.g. gpt-auto is CDP-attached to one already-running browser), so a
    plain one-shot submit — no session_id, no session_keep_alive — must not
    reach worker_host at all. It should open a session, run exactly one turn,
    and auto-close it, exactly like a keep-alive=false continued session does.
    """
    runtime, transports, tmp_path = rig

    def boom(**kwargs):  # worker_host must not be consulted for no-isolation
        raise AssertionError("worker path used for a no-isolation provider")

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        boom,
    )

    result = _dispatch(
        tmp_path,
        _running_record(tmp_path),
        dispatch_prompt="do the thing",
        provider_isolation_tier="no-isolation",
    )
    assert result["state"] == "completed", result
    assert result["session-id"] is not None
    assert len(transports) == 1
    assert transports[0].turns == ["do the thing"]
    assert transports[0].closed  # not keep-alive: ephemeral session auto-closes
