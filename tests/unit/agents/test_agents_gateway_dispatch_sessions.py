"""AS04 — sessionful dispatch routing tests (plan agent-sessions).

Real SessionRuntime + fake transport; provider/profile seams monkeypatched.
Pins: keep-alive opens and completes, session-id continues on the SAME live
transport, unsupported provider is terminal UNS-AGW-001, profile mismatch is
terminal VAL-AGW-060, and the one-shot path is untouched for plain records.
"""
from __future__ import annotations

import pytest
from tests.unit.agents.test_agents_gateway_sessions import FakeTransport, _Clock

from audiagentic.components.agents import agents_gateway_dispatch as dispatch
from audiagentic.components.agents import agents_gateway_sessions as sessions_module
from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.components.agents.agents_gateway_sessions import SessionRuntime
from audiagentic.foundation.transports import AcpLaunch

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
    transports: list[FakeTransport] = []

    def factory(launch, cwd):
        transport = FakeTransport(launch, cwd)
        transports.append(transport)
        return transport

    runtime = SessionRuntime(clock=clock, reap_interval_seconds=60, transport_factory=factory)
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    import audiagentic.components.agents.agents_api as agents_api
    import audiagentic.components.providers.services.execution as execution
    import audiagentic.components.providers.services.models as models
    import audiagentic.components.providers.services.provider_config as provider_config

    monkeypatch.setattr(agents_api, "resolve_profile", lambda root, pid: dict(PROFILE))
    monkeypatch.setattr(provider_config, "is_provider_enabled", lambda root, pid: True)
    monkeypatch.setattr(provider_config, "load_provider_config", lambda root: {"providers": {"opencode": {}}})
    monkeypatch.setattr(
        models, "resolve_model_selection",
        lambda **kwargs: {"model-id": "m1"},
    )
    monkeypatch.setattr(
        execution, "load_acp_launch_builder",
        lambda provider_id: (lambda root, model_id=None: AcpLaunch("agent")),
    )
    yield runtime, transports, tmp_path
    runtime.shutdown()


def _running_record(tmp_path, **kwargs):
    record = store.build_record(agent_profile_id="profile-1", prompt_body="hello", **kwargs)
    store.write_record(tmp_path, record)
    return store.transition_record(tmp_path, record["request-id"], "running")


def test_keep_alive_opens_session_and_completes(rig):
    runtime, transports, tmp_path = rig
    record = _running_record(tmp_path, session_keep_alive=True)
    result = dispatch.dispatch_request(tmp_path, record)
    assert result["state"] == "completed"
    assert result["session-id"] is not None
    assert result["provider-id"] == "opencode"
    assert result["completion"]["provider-session-ref"] == "prov-ses-1"
    assert len(transports) == 1
    assert transports[0].turns == ["hello"]
    assert not transports[0].closed  # keep-alive: session survives the request


def test_session_id_continues_same_live_transport(rig):
    runtime, transports, tmp_path = rig
    first = dispatch.dispatch_request(
        tmp_path, _running_record(tmp_path, session_keep_alive=True)
    )
    session_id = first["session-id"]

    second = dispatch.dispatch_request(
        tmp_path, _running_record(tmp_path, session_id=session_id)
    )
    assert second["state"] == "completed"
    assert second["session-id"] == session_id
    assert len(transports) == 1  # no second child spawned
    assert transports[0].turns == ["hello", "hello"]


def test_unsupported_provider_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig
    import audiagentic.components.providers.services.execution as execution

    monkeypatch.setattr(execution, "load_acp_launch_builder", lambda provider_id: None)
    result = dispatch.dispatch_request(
        tmp_path, _running_record(tmp_path, session_keep_alive=True)
    )
    assert result["state"] == "failed"
    assert result["error"]["code"] == "UNS-AGW-001"
    assert transports == []


def test_profile_mismatch_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig
    first = dispatch.dispatch_request(
        tmp_path, _running_record(tmp_path, session_keep_alive=True)
    )
    session_id = first["session-id"]

    import audiagentic.components.agents.agents_api as agents_api

    other = dict(PROFILE, profile_id="profile-2")
    monkeypatch.setattr(agents_api, "resolve_profile", lambda root, pid: other)
    record = store.build_record(
        agent_profile_id="profile-2", prompt_body="hi", session_id=session_id
    )
    store.write_record(tmp_path, record)
    running = store.transition_record(tmp_path, record["request-id"], "running")
    result = dispatch.dispatch_request(tmp_path, running)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-AGW-060"
    assert transports[0].turns == ["hello"]  # mismatch never reached the agent


def test_unknown_session_terminal(rig):
    runtime, transports, tmp_path = rig
    result = dispatch.dispatch_request(
        tmp_path, _running_record(tmp_path, session_id="ses_nope")
    )
    assert result["state"] == "failed"
    assert result["error"]["code"] == "RES-AGW-002"


def test_session_output_concatenates_stream_chunks():
    """agent_message_chunk fragments split mid-word — join with NO separator
    (AS07 live-gate finding: '\\n'.join corrupted 'TOKEN STORED')."""
    from types import SimpleNamespace

    def chunk(text):
        return SimpleNamespace(kind="assistant-message", text=text)

    result = SimpleNamespace(
        events=(chunk("TOKEN"), chunk(" STORE"), chunk("D"), chunk("."),
                SimpleNamespace(kind="result", text=None)),
    )
    assert dispatch._session_output_from_result(result) == "TOKEN STORED."


def test_plain_record_does_not_touch_session_path(rig, monkeypatch):
    runtime, transports, tmp_path = rig

    def boom(*args, **kwargs):  # session runtime must not be consulted
        raise AssertionError("session path used for a plain record")

    monkeypatch.setattr(sessions_module, "get_session_runtime", boom)

    import audiagentic.components.providers.services.execution as execution

    monkeypatch.setattr(
        execution, "execute_provider",
        lambda **kwargs: {"provider-id": "opencode", "model": "m1", "output": "ok"},
    )
    result = dispatch.dispatch_request(tmp_path, _running_record(tmp_path))
    assert result["state"] == "completed"
    assert transports == []
