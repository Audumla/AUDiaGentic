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

from audiagentic.components.agents import agents_gateway_dispatch as dispatch
from audiagentic.components.agents import agents_gateway_session_dispatch as session_dispatch
from audiagentic.components.agents import agents_gateway_sessions as sessions_module
from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.components.agents.agents_gateway_sessions import SessionRuntime

PROFILE = {
    "profile_id": "profile-1",
    "provider_id": "opencode",
    "model_id": "m1",
    "model_alias": None,
    "params": {},
}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock, reap_interval_seconds=60, provider_prepare_fn=fake_prepare,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    import audiagentic.components.agents.agents_api as agents_api

    monkeypatch.setattr(agents_api, "resolve_profile", lambda root, pid: dict(PROFILE))
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
    record = store.build_record(agent_profile_id="profile-1", prompt_body="hello", **kwargs)
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-test", expected_revision=0
    )
    return store.start_owned_attempt(
        tmp_path, record["request-id"], owner_epoch="service-test", worker_id="worker_test",
        expected_revision=claimed["revision"],
    )


def _dispatch(tmp_path, record, *, dispatch_prompt):
    return dispatch.dispatch_request(
        tmp_path,
        record,
        dispatch_prompt=dispatch_prompt,
        manifest_id="mf_test",
        context_fingerprint="0" * 64,
        component_profile="",
        provider_isolation_tier="full-isolation",
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
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-llm-gateway" / record["request-id"]
    assert (request_dir / "runtime" / "pi" / "manifest.json").exists()
    assert (request_dir / "runtime" / "pi" / "agent").is_dir()
    assert (request_dir / "runtime" / "pi" / "sessions").is_dir()


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


def test_unsupported_provider_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig

    # AS28 slice 4a: unsupported surface path — provider_prepare_fn returns
    # PreparedSessionTransport with transport=None, which raises CON-AGW-095.
    def unsupported_prepare(project_root, *, provider_id, surface_hint, model_id=None):

        return _build_fake_prepared(None)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime, "_provider_prepare_fn", unsupported_prepare)
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="hello")
    assert result["state"] == "failed"
    assert result["error"]["code"] == "CON-AGW-095"
    assert transports == []
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-llm-gateway" / record["request-id"]
    assert (request_dir / "quarantine" / record["request-id"] / "manifest.json").exists()


def test_profile_mismatch_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]

    import audiagentic.components.agents.agents_api as agents_api

    other = dict(PROFILE, profile_id="profile-2")
    monkeypatch.setattr(agents_api, "resolve_profile", lambda root, pid: other)
    record = store.build_record(
        agent_profile_id="profile-2", prompt_body="hi", session_id=session_id
    )
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-test", expected_revision=0
    )
    running = store.start_owned_attempt(
        tmp_path, record["request-id"], owner_epoch="service-test", worker_id="worker_test_mismatch",
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
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        lambda **kwargs: SimpleNamespace(
            result_data={"provider-id": "opencode", "model": "m1", "output": "ok"}
        ),
    )
    result = _dispatch(
        tmp_path, _running_record(tmp_path), dispatch_prompt="do the thing"
    )
    assert result["state"] == "completed", result
    assert transports == []
