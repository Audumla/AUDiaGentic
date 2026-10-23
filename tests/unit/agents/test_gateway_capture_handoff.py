from __future__ import annotations

import copy
import importlib
import multiprocessing
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway import api, store
from audiagentic.components.agents.gateway.session import capture_handoff, sessions, sessions_store
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime
from audiagentic.foundation.transports.agent_session import SessionTurnResult
from tests.unit.agents.test_agents_gateway_sessions import FakeAgentSessionTransport, _build_fake_prepared


def _running(root, session_id):
    record = store.build_record(
        execution_profile_id="profile-1", prompt_body="first", session_id=session_id,
        provider_transport_kind="provider-session",
    )
    store.write_record(root, record)
    claimed = store.claim_dispatch(root, record["request-id"], owner_epoch="service", expected_revision=0)
    return store.start_owned_attempt(
        root, record["request-id"], owner_epoch="service", worker_id="worker",
        expected_revision=claimed["revision"],
    )


def _checkpoint(request_id):
    return {
        "unresolved-turn-id": request_id, "unresolved-turn-pending": True,
        "submission-attempt-id": "attempt", "prompt-text-digest": "digest",
        "submission-state": "proven", "submission-stage": "send-click-acknowledged",
        "submission-proven": True, "send-intent-ever": True,
        "submission-proof-source": "provider-user-message",
    }


def _capture(root, running, session):
    return store.transition_operator_terminal(
        root, running["request-id"], expected_revision=running["revision"],
        updates={"__final-response-text": "captured answer", "completion": {"source": "operator-provider-capture"}},
        session_id=session["session-id"], expected_session_provider=session["provider"],
        expected_session_binding=session.get("binding"), clear_unresolved_turn=True,
    )


@pytest.mark.parametrize("foreign", [False, True])
def test_capture_checkpoint_projection_is_opt_in_and_same_request_only(foreign):
    from audiagentic.components.agents.gateway.queue.recovery import resolve_effective_turn_evidence
    record = {"request-id": "req_current", "provider-metadata": {"chat-url": "retained"}}
    canonical = {"unresolved-turn-id": "req_other" if foreign else "req_current", "submission-attempt-id": "canonical-attempt"}
    ordinary = resolve_effective_turn_evidence(record, canonical)
    expanded = resolve_effective_turn_evidence(record, canonical, include_checkpoint_identity=True)
    assert "submission-attempt-id" not in ordinary
    if foreign:
        assert expanded == record["provider-metadata"]
    else:
        assert expanded["submission-attempt-id"] == "canonical-attempt"


@pytest.mark.parametrize("invalid", [None, "owner", "provenance", "artifact", "checkpoint", "binding", "pending", "session"])
def test_handoff_requires_durable_exact_capture_authority(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: None)
    running = _running(tmp_path, "ses-handoff-authority")
    session = sessions_store.build_session_record(
        session_id=running["session-id"], created_by_request_id=running["request-id"],
        execution_profile_id="profile-1", provider_id="opencode",
        provider_metadata=_checkpoint(running["request-id"]),
    )
    sessions_store.write_session_record(tmp_path, session)
    completed = _capture(tmp_path, running, session)
    cleared = sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, session["session-id"]))
    assert not (sessions_store._RECOVERY_CHECKPOINT_KEYS.intersection(cleared) - {"unresolved-turn-pending", "recovery-state"})
    owner = capture_handoff.capture_owner(running)
    if invalid == "owner":
        owner = {**owner, "attempt-epoch": owner["attempt-epoch"] + 1}
    elif invalid == "provenance":
        completed["completion"] = {"source": "provider"}
    elif invalid == "artifact":
        completed["response-artifact"]["sha256"] = "0" * 64
    elif invalid == "checkpoint":
        completed["terminal-finalization"]["pre-clear-checkpoint"]["unresolved-turn-id"] = "req_other"
    elif invalid in {"binding", "pending"}:
        changed = sessions_store.read_session_record(tmp_path, session["session-id"])
        if invalid == "binding":
            from audiagentic.components.agents.gateway.session import bindings
            changed["binding"] = bindings.build_binding(provider_id="opencode", provider_session_ref="other", surface_id="opencode-acp", generation=2)
        else:
            changed["provider"]["metadata"]["unresolved-turn-pending"] = True
        sessions_store.write_session_record(tmp_path, changed)
    if invalid in {"provenance", "artifact", "checkpoint"}:
        store.write_record(tmp_path, completed)
    try:
        result = capture_handoff.read_captured_handoff(
            tmp_path, running["request-id"], "other-session" if invalid == "session" else session["session-id"], owner,
        )
    except Exception:
        if invalid != "artifact":
            raise
        result = None
    assert (result is not None) is (invalid is None)


def _capture_in_other_process(root, running, session, connection):
    try:
        completed = _capture(Path(root), running, session)
        connection.send(completed["state"])
    except Exception as exc:
        connection.send((type(exc).__name__, str(exc)))
    finally:
        connection.close()


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("failure_mode", ["none", "memory", "ack"])
def test_active_capture_releases_fifo_after_memory_reconciliation(tmp_path, monkeypatch, remote, failure_mode):
    started = threading.Event()
    allow_reconciliation = threading.Event()
    if failure_mode == "none":
        allow_reconciliation.set()
    acknowledge = capture_handoff.acknowledge_captured_handoff
    def guarded_ack(*args, **kwargs):
        if failure_mode == "ack" and not allow_reconciliation.is_set():
            return False
        return acknowledge(*args, **kwargs)
    monkeypatch.setattr(capture_handoff, "acknowledge_captured_handoff", guarded_ack)
    results = {}
    errors = []

    class ObservedTransport(FakeAgentSessionTransport):
        supports_external_completion = True
        memory_ready = False
        checkpoint = None

        async def prompt(self, request, sink):
            self.turns.append(request.body)
            if request.body == "first":
                assert request.completion_token is not None
                started.set()
                await request.completion_token.wait()
                return SessionTurnResult(request.turn_id, "externally-captured", 0, 0)
            assert self.memory_ready, "successor entered before captured memory reconciliation"
            return SessionTurnResult(request.turn_id, "end-turn", 0, 0)

        def synchronize_cleared_predecessor_checkpoint(self, predecessor, expected, persisted):
            assert runtime._handles[self.ag_session_id].turn_lock.locked()
            assert expected == self.checkpoint
            assert predecessor == expected["unresolved-turn-id"]
            assert persisted["unresolved-turn-pending"] is False
            if failure_mode == "memory" and not allow_reconciliation.is_set():
                return False
            self.memory_ready = True
            return True

    transport = ObservedTransport()
    def prepare(root, **kwargs):
        transport.ag_session_id = kwargs["ag_session_id"]
        return _build_fake_prepared(transport)
    runtime = SessionRuntime(provider_prepare_fn=prepare, reap_interval_seconds=60)
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: runtime)
    first = second = None
    process = parent = child = None
    try:
        session = runtime.open_session(tmp_path, execution_profile_id="profile-1", provider_id="opencode", model_id="m1", surface_hint=None)
        running = _running(tmp_path, session["session-id"])
        session = sessions_store.read_session_record(tmp_path, session["session-id"])
        checkpoint = _checkpoint(running["request-id"])
        session["provider"].setdefault("metadata", {}).update(checkpoint)
        sessions_store.write_session_record(tmp_path, session)
        transport.checkpoint = copy.deepcopy(checkpoint)
        def invoke(key, body, request_id):
            try:
                results[key] = runtime.prompt_in_session(tmp_path, session["session-id"], body, request_id=request_id)
            except BaseException as exc:
                errors.append(exc)
        first = threading.Thread(target=invoke, args=("first", "first", running["request-id"]))
        second = threading.Thread(target=invoke, args=("second", "second", "req-followup"))
        first.start()
        assert started.wait(3)
        second.start()
        if remote:
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            worker = importlib.import_module("tests.unit.agents.test_gateway_capture_handoff")._capture_in_other_process
            process = context.Process(target=worker, args=(str(tmp_path), running, session, child))
            process.start()
            child.close()
            assert parent.poll(15), "remote capture did not finish"
            assert parent.recv() == "completed"
            process.join(5)
            assert process.exitcode == 0
        else:
            _capture(tmp_path, running, session)
        first.join(5)
        if failure_mode != "none":
            assert not first.is_alive()
            assert second.is_alive()
            assert transport.turns == ["first"]
            if failure_mode == "ack":
                assert transport.memory_ready, "memory succeeded but ACK must still fence admission"
            assert runtime.session_runtime_status(session["session-id"])["capture-handoff-pending"] is True
            assert store.read_record(tmp_path, running["request-id"]).get("terminal-finalization")
            assert api.get_execution_response(tmp_path, running["request-id"]) == "captured answer"
            allow_reconciliation.set()
        second.join(5)
        assert not first.is_alive() and not second.is_alive()
        assert errors == []
        assert results["first"].stop_reason == "externally-captured"
        assert results["second"].stop_reason == "end-turn"
        assert transport.turns == ["first", "second"]
        completed = store.read_record(tmp_path, running["request-id"])
        assert completed["state"] == "completed"
        assert "terminal-finalization" not in completed
        assert api.get_execution_response(tmp_path, running["request-id"]) == "captured answer"
        final_session = sessions_store.read_session_record(tmp_path, session["session-id"])
        assert final_session["activity"]["turn-count"] == 2
        assert final_session["provider"]["metadata"]["unresolved-turn-pending"] is False
    finally:
        allow_reconciliation.set()
        if process is not None and process.is_alive():
            process.terminate()
            process.join(5)
        if parent is not None:
            parent.close()
        runtime.shutdown()
        for thread in (first, second):
            if thread is not None:
                thread.join(3)


@pytest.mark.parametrize("disposition", ["acknowledged", "busy", "missing-runtime", "corrupt-artifact"])
def test_idle_replay_preserves_marker_until_unlocked_memory_ack(tmp_path, monkeypatch, disposition):
    from audiagentic.components.agents.agents_paths import gateway_request_path
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: None)
    running = _running(tmp_path, "ses-replayed-capture")
    session = sessions_store.build_session_record(
        session_id=running["session-id"], created_by_request_id=running["request-id"],
        execution_profile_id="profile-1", provider_id="opencode", provider_metadata=_checkpoint(running["request-id"]),
    )
    sessions_store.write_session_record(tmp_path, session)
    completed = _capture(tmp_path, running, session)
    marker = completed["terminal-finalization"]
    callbacks = []
    def synchronize(session_id, request_id, **kwargs):
        from audiagentic.foundation.system.process import StartupLock
        # Retention can briefly own this file from another thread. Reacquire
        # it here to prove the caller released its own non-reentrant lock.
        with StartupLock(gateway_request_path(tmp_path, request_id).with_name("mutation.lock"), timeout=1):
            pass
        callbacks.append(request_id)
        assert kwargs["expected_metadata"] == marker["pre-clear-checkpoint"]
        return disposition == "acknowledged"
    if disposition != "missing-runtime":
        monkeypatch.setattr(sessions, "peek_session_runtime", lambda: SimpleNamespace(synchronize_cleared_predecessor_checkpoint=synchronize))
    if disposition == "corrupt-artifact":
        completed["response-artifact"]["sha256"] = "0" * 64
        store.write_record(tmp_path, completed)
    assert store.repair_pending_terminal_finalization(tmp_path, running["request-id"]) is (disposition == "acknowledged")
    current = store.read_record(tmp_path, running["request-id"])
    assert ("terminal-finalization" in current) is (disposition != "acknowledged")
    assert store.repair_pending_terminal_finalization(tmp_path, running["request-id"]) is False
    assert len(callbacks) == (1 if disposition == "acknowledged" else 2 if disposition == "busy" else 0)


@pytest.mark.parametrize("binding_changed", [False, True])
def test_ack_revalidates_binding_and_is_idempotent_without_extra_write(tmp_path, monkeypatch, binding_changed):
    from audiagentic.components.agents.gateway.session import bindings
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: None)
    running = _running(tmp_path, "ses-ack-cas")
    session = sessions_store.build_session_record(
        session_id=running["session-id"], created_by_request_id=running["request-id"],
        execution_profile_id="profile-1", provider_id="opencode", provider_metadata=_checkpoint(running["request-id"]),
    )
    sessions_store.write_session_record(tmp_path, session)
    completed = _capture(tmp_path, running, session)
    marker = completed["terminal-finalization"]
    if binding_changed:
        changed = sessions_store.read_session_record(tmp_path, session["session-id"])
        changed["binding"] = bindings.build_binding(provider_id="opencode", provider_session_ref="successor", surface_id="opencode-acp", generation=2)
        sessions_store.write_session_record(tmp_path, changed)
    assert capture_handoff.acknowledge_captured_handoff(tmp_path, running["request-id"], marker) is (not binding_changed)
    after = store.read_record(tmp_path, running["request-id"])
    assert ("terminal-finalization" in after) is binding_changed
    revision = after["revision"]
    assert capture_handoff.acknowledge_captured_handoff(tmp_path, running["request-id"], marker) is (not binding_changed)
    assert store.read_record(tmp_path, running["request-id"])["revision"] == revision
