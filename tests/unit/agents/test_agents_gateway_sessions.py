"""AS02/AS03 — SessionRuntime + session store tests (plan agent-sessions).

Fake transport (no subprocess) + injected clock + fast reap interval give
deterministic coverage of the lifecycle guarantees: open/turn/close, idle
and max-lifetime reaping, busy rejection, dead-child failure, shutdown.
"""
from __future__ import annotations

import functools
import multiprocessing
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.agents import agents_gateway_session_bindings as binding_store
from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_gateway_sessions import SessionRuntime
from audiagentic.components.agents.agents_paths import gateway_session_binding_index_path
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports import AcpLaunch, AcpResult


class FakeTransport:
    """Transport double: no child process, scriptable liveness and blocking."""

    def __init__(self, launch, cwd) -> None:
        self.launch = launch
        self.cwd = cwd
        self.opened = False
        self.closed = False
        self.alive = False
        self.turns: list[str] = []
        self.block_event: threading.Event | None = None
        # AS18: optional on_event emitter for intra-turn events
        self.on_event_emitter: Any = None  # callable((on_event, session_id) -> None)
        self.provider_session_ref = "prov-ses-1"

    async def open(self) -> str:
        self.opened = True
        self.alive = True
        return self.provider_session_ref

    def is_alive(self) -> bool:
        return self.alive and not self.closed

    async def prompt(self, prompt: str, **kwargs) -> AcpResult:
        cancel_signal = kwargs.get("cancel_signal")
        stop_reason = "end_turn"
        if self.block_event is not None:
            import asyncio
            while not self.block_event.is_set():
                # RV680: honor protocol-level cancel like the real transport.
                if cancel_signal is not None and cancel_signal.is_set():
                    stop_reason = "cancelled"
                    break
                # close() aborts an in-flight turn, like the real transport.
                if self.closed:
                    raise AudiaGenticError(
                        code="EXT-ACP-001", kind="execution",
                        message="transport closed mid-turn", details={},
                    )
                await asyncio.sleep(0.01)
        self.turns.append(prompt)
        # AS18: fire intra-turn events if emitter is configured
        on_event = kwargs.get("on_event")
        if on_event and self.on_event_emitter:
            await self.on_event_emitter(on_event, "prov-ses-1")
        return AcpResult(
            session_id="prov-ses-1",
            stop_reason=stop_reason,
            events=(),
            total_events=1,
            dropped_events=0,
            bytes_buffered=0,
            terminal_event=None,
            callback_disabled=False,
        )

    async def close(self) -> None:
        self.closed = True
        self.alive = False


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def rig(tmp_path):
    """(runtime, clock, transports) with a fast reaper; shut down after test."""
    clock = _Clock()
    transports: list[FakeTransport] = []
    counter = 0

    def factory(launch, cwd):
        nonlocal counter
        counter += 1
        transport = FakeTransport(launch, cwd)
        transport.provider_session_ref = f"prov-ses-{counter}"
        transports.append(transport)
        return transport

    runtime = SessionRuntime(clock=clock, reap_interval_seconds=0.05, transport_factory=factory)
    yield runtime, clock, transports, tmp_path
    runtime.shutdown()


def _open(runtime, tmp_path, **kwargs) -> dict[str, Any]:
    return runtime.open_session(
        tmp_path,
        agent_profile_id="profile-1",
        launch=AcpLaunch("agent"),
        provider_id="opencode",
        model_id="m1",
        **kwargs,
    )


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_open_prompt_close_lifecycle(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    assert record["state"] == "active"
    assert record["contract-version"] == "v2"
    assert record["binding"]["provider-session-ref"] == "prov-ses-1"
    assert "provider-session-ref" not in binding_store.public_binding_projection(record["binding"])
    assert runtime.live_session_ids() == [session_id]

    result = runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert result.stop_reason == "end_turn"
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["turn-count"] == 1
    assert stored["request-ids"] == ["req_1"]

    closed = runtime.close_session(tmp_path, session_id)
    assert closed["state"] == "closed"
    assert closed["close-reason"] == "client-request"
    assert transports[0].closed
    assert runtime.live_session_ids() == []


def test_close_is_idempotent(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    runtime.close_session(tmp_path, record["session-id"])
    again = runtime.close_session(tmp_path, record["session-id"])
    assert again["state"] == "closed"


def test_prompt_on_unknown_session_raises(rig):
    runtime, clock, transports, tmp_path = rig
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.prompt_in_session(tmp_path, "ses_missing", "hello")


def test_idle_timeout_reaps_session(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=100)
    session_id = record["session-id"]
    clock.now += 101  # beyond idle timeout
    assert _wait_for(lambda: runtime.live_session_ids() == [])
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "expired"
    assert stored["close-reason"] == "idle-timeout"
    assert transports[0].closed


def test_max_lifetime_reaps_even_recently_active(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=10_000, max_lifetime_seconds=200)
    session_id = record["session-id"]
    clock.now += 150
    runtime.prompt_in_session(tmp_path, session_id, "keep busy")  # refreshes idle clock
    clock.now += 60  # total age 210 > 200, idle only 60
    assert _wait_for(lambda: runtime.live_session_ids() == [])
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "expired"
    assert stored["close-reason"] == "max-lifetime"


def test_concurrent_prompts_queue_fifo(rig):
    """Turns on a busy session queue and run in order (RV513), not reject."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    results: list[Any] = []

    def turn(prompt):
        results.append(runtime.prompt_in_session(tmp_path, session_id, prompt))

    first = threading.Thread(target=turn, args=("first",))
    second = threading.Thread(target=turn, args=("second",))
    first.start()
    time.sleep(0.1)  # first turn is in flight (blocked on the gate)
    second.start()
    time.sleep(0.1)  # second turn is queued behind it
    assert results == []  # nothing rejected, nothing finished yet
    gate.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert transports[0].turns == ["first", "second"]
    assert len(results) == 2


def test_session_snapshot_all_reports_active_turn(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    result: list[Any] = []
    worker = threading.Thread(
        target=lambda: result.append(
            runtime.prompt_in_session(tmp_path, session_id, "snapshot", request_id="req_snap_1")
        )
    )
    worker.start()
    time.sleep(0.1)

    snapshot = runtime.session_snapshot_all()
    assert snapshot == {
        session_id: {
            "turn-active": True,
            "pending-turns": 0,
            "current-request-id": "req_snap_1",
        }
    }

    gate.set()
    worker.join(timeout=2)
    assert result and result[0].stop_reason == "end_turn"


def test_turn_queue_full_rejects(rig, tmp_path):
    clock = _Clock()
    transports: list[FakeTransport] = []

    def factory(launch, cwd):
        transport = FakeTransport(launch, cwd)
        transports.append(transport)
        return transport

    runtime = SessionRuntime(
        clock=clock, reap_interval_seconds=60, transport_factory=factory,
        session_queue_max=1,
    )
    try:
        record = _open(runtime, tmp_path)
        session_id = record["session-id"]
        gate = threading.Event()
        transports[0].block_event = gate

        threads = [
            threading.Thread(
                target=lambda p=p: _swallow(lambda: runtime.prompt_in_session(tmp_path, session_id, p))
            )
            for p in ("running", "queued")
        ]
        threads[0].start()
        time.sleep(0.1)  # in flight
        threads[1].start()
        time.sleep(0.1)  # one waiter — queue (max 1) now full
        with pytest.raises(AudiaGenticError, match="CON-AGW-003"):
            runtime.prompt_in_session(tmp_path, session_id, "overflow")
        gate.set()
        for thread in threads:
            thread.join(timeout=2)
        assert transports[0].turns == ["running", "queued"]
    finally:
        runtime.shutdown()


def _swallow(fn):
    try:
        fn()
    except Exception:
        pass


def test_zero_bounds_disable_reaping(rig):
    """idle-timeout 0 and max-lifetime 0 opt the session out of both caps."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=0, max_lifetime_seconds=0)
    session_id = record["session-id"]
    clock.now += 1_000_000  # far past any default bound
    time.sleep(0.3)  # several reaper sweeps
    assert runtime.live_session_ids() == [session_id]
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "active"


def test_reaper_never_closes_processing_session(rig):
    """A session past max lifetime drains: the in-flight turn completes, new
    turns are rejected (CON-AGW-004), then the reaper closes it (RV513)."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, max_lifetime_seconds=100, idle_timeout_seconds=10_000)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    results: list[Any] = []
    thread = threading.Thread(
        target=lambda: results.append(runtime.prompt_in_session(tmp_path, session_id, "long turn"))
    )
    thread.start()
    time.sleep(0.1)  # turn in flight
    clock.now += 200  # past max lifetime while processing
    time.sleep(0.2)  # reaper sweeps — must NOT close the busy session
    assert runtime.live_session_ids() == [session_id]

    with pytest.raises(AudiaGenticError, match="CON-AGW-004"):
        runtime.prompt_in_session(tmp_path, session_id, "too late")

    gate.set()
    thread.join(timeout=2)
    assert results and results[0].stop_reason == "end_turn"  # turn finished intact
    assert _wait_for(lambda: runtime.live_session_ids() == [])  # then reaped
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "expired"
    assert stored["close-reason"] == "max-lifetime"


def test_dead_child_fails_session(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].alive = False  # child died out-of-band
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.prompt_in_session(tmp_path, session_id, "hello")
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "failed"
    assert runtime.live_session_ids() == []


def test_shutdown_closes_all_sessions(rig):
    runtime, clock, transports, tmp_path = rig
    first = _open(runtime, tmp_path)
    second = _open(runtime, tmp_path)
    runtime.shutdown()
    for record in (first, second):
        stored = session_store.read_session_record(tmp_path, record["session-id"])
        assert stored["state"] == "closed"
        assert stored["close-reason"] == "shutdown"
    assert all(t.closed for t in transports)
    with pytest.raises(AudiaGenticError, match="CON-AGW-002"):
        _open(runtime, tmp_path)


def test_api_list_and_close_sessions(rig, monkeypatch):
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    listed = api.list_llm_sessions(tmp_path)
    assert [s["session-id"] for s in listed] == [record["session-id"]]
    assert listed[0]["live"] is True
    assert "provider-session-ref" not in repr(listed)
    assert listed[0]["binding"]["provider-ref-key-prefix"]

    closed = api.close_llm_session(tmp_path, record["session-id"])
    assert closed["state"] == "closed"
    assert api.list_llm_sessions(tmp_path)[0]["live"] is False
    # Idempotent on an already-terminal session
    again = api.close_llm_session(tmp_path, record["session-id"])
    assert again["state"] == "closed"


def test_api_close_orphaned_session_marks_failed(rig, monkeypatch):
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    # Persisted active, but no live handle (simulates a previous process)
    record = session_store.build_session_record(agent_profile_id="profile-1")
    session_store.write_session_record(tmp_path, record)

    closed = api.close_llm_session(tmp_path, record["session-id"])
    assert closed["state"] == "failed"
    assert closed["close-reason"] == "orphaned"


def test_session_record_validation():
    with pytest.raises(AudiaGenticError, match="VAL-AGW-050"):
        session_store.build_session_record(agent_profile_id="p", idle_timeout_seconds=-1)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-051"):
        session_store.build_session_record(agent_profile_id="p", max_lifetime_seconds=-5)
    # 0 disables a bound — valid (RV513)
    record = session_store.build_session_record(
        agent_profile_id="p", idle_timeout_seconds=0, max_lifetime_seconds=0
    )
    assert record["idle-timeout-seconds"] == 0
    assert record["max-lifetime-seconds"] == 0


def test_cross_process_session_turn_appends_do_not_lose_updates(tmp_path: Path) -> None:
    """RV733: session mutation now uses the foundation StartupLock (like
    request records), so concurrent processes recording turns on the same
    session cannot lose an update — every request-id and the turn-count
    both reflect all N appends."""
    record = session_store.build_session_record(agent_profile_id="p")
    session_store.write_session_record(tmp_path, record)
    session_id = record["session-id"]
    context = multiprocessing.get_context("spawn")
    count = 12
    processes = [
        context.Process(
            target=functools.partial(
                session_store.record_session_turn,
                tmp_path,
                session_id,
                f"req_{index}",
            ),
        )
        for index in range(count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)

    assert [process.exitcode for process in processes] == [0] * count
    final = session_store.read_session_record(tmp_path, session_id)
    assert final["turn-count"] == count
    assert sorted(final["request-ids"]) == sorted(f"req_{index}" for index in range(count))


def test_v1_session_record_migrates_to_v2_binding(tmp_path):
    import json

    legacy = {
        "contract-version": "v1",
        "session-id": "ses_legacy",
        "agent-profile-id": "p",
        "provider-id": "opencode",
        "model-id": "m",
        "provider-session-ref": "secret-ref",
        "state": "active",
        "close-reason": None,
        "idle-timeout-seconds": None,
        "max-lifetime-seconds": None,
        "request-ids": [],
        "turn-count": 0,
        "error": None,
        "created-at": "2026-01-01T00:00:00Z",
        "updated-at": "2026-01-01T00:00:00Z",
        "last-activity-at": "2026-01-01T00:00:00Z",
        "closed-at": None,
    }
    path = tmp_path / "runtime" / "agent-llm-gateway" / "sessions" / "ses_legacy" / "record.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = session_store.read_session_record(tmp_path, "ses_legacy")
    assert migrated["contract-version"] == "v2"
    assert "provider-session-ref" not in migrated
    assert migrated["binding"]["provider-session-ref"] == "secret-ref"
    assert migrated["binding"]["relation"] == "opened"
    assert migrated["binding"]["ownership"] == "owned"


def test_binding_index_uses_hash_not_raw_ref(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    text = gateway_session_binding_index_path(tmp_path).read_text(encoding="utf-8")
    assert "prov-ses-1" not in text
    assert record["binding"]["provider-ref-key"] in text


def test_duplicate_owned_binding_rolls_back_transport(tmp_path):
    clock = _Clock()
    transports: list[FakeTransport] = []

    def factory(launch, cwd):
        transport = FakeTransport(launch, cwd)
        transport.provider_session_ref = "same-ref"
        transports.append(transport)
        return transport

    runtime = SessionRuntime(clock=clock, reap_interval_seconds=60, transport_factory=factory)
    try:
        _open(runtime, tmp_path)
        with pytest.raises(AudiaGenticError, match="CON-AGW-096"):
            _open(runtime, tmp_path)
        assert transports[1].closed
    finally:
        runtime.shutdown()


def test_closed_owned_binding_allows_later_same_ref(tmp_path):
    clock = _Clock()
    transports: list[FakeTransport] = []

    def factory(launch, cwd):
        transport = FakeTransport(launch, cwd)
        transport.provider_session_ref = "same-ref"
        transports.append(transport)
        return transport

    runtime = SessionRuntime(clock=clock, reap_interval_seconds=60, transport_factory=factory)
    try:
        first = _open(runtime, tmp_path)
        runtime.close_session(tmp_path, first["session-id"])
        second = _open(runtime, tmp_path)
        assert second["binding"]["provider-session-ref"] == "same-ref"
        assert second["session-id"] != first["session-id"]
    finally:
        runtime.shutdown()


def test_request_record_session_field_validation():
    from audiagentic.components.agents import agents_gateway_store as store

    # session_idle_timeout without keep_alive still rejected (VAL-AGW-059)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-059"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_idle_timeout_seconds=60,
        )
    # session_max_lifetime without keep_alive still rejected (VAL-AGW-061)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_max_lifetime_seconds=60,  # requires keep-alive
        )
    # Negative max_lifetime rejected
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_keep_alive=True, session_max_lifetime_seconds=-1,
        )
    # New session with keep-alive and bounds (unchanged)
    record = store.build_record(
        agent_profile_id="p", prompt_body="x",
        session_keep_alive=True, session_idle_timeout_seconds=60,
        session_max_lifetime_seconds=0,  # 0 = no lifetime cap (RV513)
    )
    assert record["session-keep-alive"] is True
    assert record["session-idle-timeout-seconds"] == 60
    assert record["session-max-lifetime-seconds"] == 0


def test_session_id_with_keep_alive_allowed():
    """session_id + session_keep_alive=true is valid: continue session and
    leave it live after the turn."""
    from audiagentic.components.agents import agents_gateway_store as store

    record = store.build_record(
        agent_profile_id="p", prompt_body="x",
        session_id="ses_1", session_keep_alive=True,
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is True


def test_session_id_with_keep_alive_omitted_is_none():
    """session_id without keep_alive (omitted) stores None — preserves
    existing behavior: continued session stays live after the turn."""
    from audiagentic.components.agents import agents_gateway_store as store

    record = store.build_record(
        agent_profile_id="p", prompt_body="x",
        session_id="ses_1",
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is None


def test_session_id_with_keep_alive_false_allowed():
    """session_id + session_keep_alive=false is valid: continue session and
    close it after the turn if quiescent."""
    from audiagentic.components.agents import agents_gateway_store as store

    record = store.build_record(
        agent_profile_id="p", prompt_body="x",
        session_id="ses_1", session_keep_alive=False,
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is False


def test_session_id_with_keep_alive_and_bounds_allowed():
    """session_id + keep_alive=true + bounds is valid: continue session,
    update its lifetime policy after the turn."""
    from audiagentic.components.agents import agents_gateway_store as store

    record = store.build_record(
        agent_profile_id="p", prompt_body="x",
        session_id="ses_1",
        session_keep_alive=True,
        session_idle_timeout_seconds=120,
        session_max_lifetime_seconds=3600,
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is True
    assert record["session-idle-timeout-seconds"] == 120
    assert record["session-max-lifetime-seconds"] == 3600


def test_session_id_with_keep_alive_false_and_bounds_rejected():
    """session_id + keep_alive=false + bounds is rejected: without
    keep-alive, no lifetime policy update happens after the turn, so bounds
    are meaningless."""
    from audiagentic.components.agents import agents_gateway_store as store

    with pytest.raises(AudiaGenticError, match="VAL-AGW-059"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_id="ses_1",
            session_keep_alive=False,
            session_idle_timeout_seconds=60,
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_id="ses_1",
            session_keep_alive=False,
            session_max_lifetime_seconds=3600,
        )


def test_update_session_bounds_on_live_handle(rig):
    """update_session_bounds mutates the in-memory handle's timeout fields."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=100, max_lifetime_seconds=200)
    session_id = record["session-id"]

    # Verify initial bounds
    snapshot = runtime.session_snapshot_all()
    assert snapshot[session_id]  # handle exists

    # Update bounds via runtime API
    runtime.update_session_bounds(
        session_id,
        idle_timeout_seconds=500,
        max_lifetime_seconds=1000,
    )

    # Verify the handle's bounds changed by checking reaping behavior.
    # After update, idle timeout is 500 (was 100). Advance clock past 200
    # but not past 500 — session should still be alive.
    clock.now += 200  # past original 100s idle, within new 500s
    time.sleep(0.3)  # several reaper sweeps
    assert runtime.live_session_ids() == [session_id]

    runtime.close_session(tmp_path, session_id)


def test_update_session_bounds_unknown_session_raises(rig):
    """update_session_bounds on a non-live session raises RES-AGW-003."""
    runtime, clock, transports, tmp_path = rig
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.update_session_bounds("ses_nonexistent", idle_timeout_seconds=100)


def test_session_is_quiescent_true_when_no_turns(rig):
    """session_is_quiescent returns True when no turn is active or queued."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    assert runtime.session_is_quiescent(session_id) is True
    runtime.close_session(tmp_path, session_id)


def test_session_is_quiescent_false_during_active_turn(rig):
    """session_is_quiescent returns False while a turn is running."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    def _turn():
        runtime.prompt_in_session(tmp_path, session_id, "busy")

    worker = threading.Thread(target=_turn)
    worker.start()
    time.sleep(0.1)  # turn is in flight
    assert runtime.session_is_quiescent(session_id) is False

    gate.set()
    worker.join(timeout=2)
    # After turn completes, should be quiescent again
    time.sleep(0.05)
    assert runtime.session_is_quiescent(session_id) is True
    runtime.close_session(tmp_path, session_id)


def test_session_is_quiescent_nonexistent_returns_true(rig):
    """session_is_quiescent returns True for a session that isn't live —
    treating it as already closed for post-turn close purposes."""
    runtime, clock, transports, tmp_path = rig
    assert runtime.session_is_quiescent("ses_nonexistent") is True


def test_session_lifecycle_events_published(rig, monkeypatch):
    """A subscriber sees the full lifecycle: opened → turn-finished → closed."""
    runtime, clock, transports, tmp_path = rig

    events_captured: list[tuple[str, dict]] = []

    def fake_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        events_captured.append((topic, payload))

    from audiagentic.foundation import event as event_mod
    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(fake_publish))

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    # opened event
    assert len(events_captured) == 1
    topic, payload = events_captured[0]
    assert topic == "agents.session.opened"
    assert payload["session-id"] == session_id
    assert payload["agent-profile-id"] == "profile-1"
    assert payload["state"] == "active"
    assert payload["provider-id"] == "opencode"
    assert payload["model-id"] == "m1"

    # turn-finished event
    runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert len(events_captured) == 2
    topic, payload = events_captured[1]
    assert topic == "agents.session.turn-finished"
    assert payload["session-id"] == session_id
    assert payload["state"] == "active"
    assert payload["request-id"] == "req_1"
    assert payload["turn-count"] == 1
    assert payload["stop-reason"] == "end_turn"

    # closed event
    runtime.close_session(tmp_path, session_id)
    assert len(events_captured) == 3
    topic, payload = events_captured[2]
    assert topic == "agents.session.closed"
    assert payload["state"] == "closed"
    assert payload["close-reason"] == "client-request"
    assert payload["turn-count"] == 1


def test_publish_failure_does_not_break_session_lifecycle(rig, monkeypatch):
    """Publish failure does not break the session loop — open/close/prompt succeed."""
    runtime, clock, transports, tmp_path = rig

    def raising_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        raise RuntimeError("bus is down")

    from audiagentic.foundation import event as event_mod
    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(raising_publish))

    # Open succeeds despite publish failure
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    assert record["state"] == "active"

    # Prompt succeeds despite publish failure
    result = runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert result.stop_reason == "end_turn"

    # Close succeeds despite publish failure
    closed = runtime.close_session(tmp_path, session_id)
    assert closed["state"] == "closed"


class _FakeBus:
    def __init__(self, publish_fn) -> None:
        self._publish_fn = publish_fn

    def publish(self, topic: str, payload: dict, metadata: dict | None = None) -> None:
        return self._publish_fn(topic, payload, metadata)


def test_intra_turn_events_wired_to_eventbus(rig, monkeypatch):
    """AS18 — on_event callback publishes normalized events during prompt."""
    runtime, clock, transports, tmp_path = rig

    events_captured: list[tuple[str, dict]] = []

    def capture_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        events_captured.append((topic, {**payload, "_metadata": metadata or {}}))

    from audiagentic.foundation import event as event_mod
    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(capture_publish))

    # Configure the fake transport to emit CANONICAL intra-turn events, the
    # way the real transport does post-RV679 (raw kinds live in ext only).
    async def _emit_test_events(on_event, session_id):
        from audiagentic.foundation.transports.acp import AcpEvent
        for i, (kind, terminal, ext) in enumerate([
            ("thought", False, {"acp": {"raw_kind": "agent_thought_chunk"}}),
            ("thought", False, {"acp": {"raw_kind": "agent_thought_chunk"}}),  # deduped
            ("tool-call", False, {"acp": {"raw_kind": "tool_call", "status": "pending", "tool_call_id": "tc1"}}),
            ("tool-call", False, {"acp": {"raw_kind": "tool_call_update", "status": "in_progress", "tool_call_id": "tc1"}}),  # deduped
            ("tool-call", False, {"acp": {"raw_kind": "tool_call_update", "status": "failed", "tool_call_id": "tc1"}}),
            ("result", True, {"acp": {"stop_reason": "end_turn"}}),
        ]):
            evt = AcpEvent(
                sequence=i + 1, kind=kind, timestamp="2025-01-01T00:00:00Z",
                session_id=session_id, text=None, terminal=terminal, error=None, ext=ext,
            )
            result = on_event(evt)
            if result is not None:
                await result

    record = _open(runtime, tmp_path)
    transports[0].on_event_emitter = _emit_test_events  # transport created by open
    session_id = record["session-id"]
    events_captured.clear()  # clear open event

    result = runtime.prompt_in_session(
        tmp_path,
        session_id,
        "hello",
        request_id="req_1",
        correlation_id="corr_1",
    )
    assert result.stop_reason == "end_turn"

    # Verify the normalized turn events were published, deduped, and terminal-aware
    turn_topics = [(t, p) for t, p in events_captured if t.startswith("agents.turn.")]
    assert [t for t, _ in turn_topics] == [
        "agents.turn.model.started",
        "agents.turn.tool.started",
        "agents.turn.tool.completed",
        "agents.turn.model.completed",
    ], f"unexpected projection: {turn_topics}"

    # Check correlation: session-id and request-id are present; strength/tier
    # are honestly unknown until AS19 declaration-driven resolution lands.
    for topic, payload in turn_topics:
        assert payload["session-id"] == session_id
        assert payload["request-id"] == "req_1"
        assert payload["agent-profile-id"] is not None
        assert payload["semantic-strength"] == "unknown"
        assert payload["verification-tier"] == "unknown"
        assert payload["_metadata"] == {"correlation_id": "corr_1"}

    # Verify native_kind is preserved and tool failure is observable
    model_event = [p for t, p in turn_topics if t == "agents.turn.model.started"][0]
    assert model_event.get("native_kind") == "agent_thought_chunk"
    tool_completed = [p for t, p in turn_topics if t == "agents.turn.tool.completed"][0]
    assert tool_completed["status"] == "failed"
    assert tool_completed["tool-call-id"] == "tc1"

    runtime.close_session(tmp_path, session_id)


def test_turn_event_publish_failure_does_not_break_prompt(rig, monkeypatch):
    """AS18 — publish failure in on_event callback does not break the prompt."""
    runtime, clock, transports, tmp_path = rig

    def raising_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        raise RuntimeError("bus is down")

    from audiagentic.foundation import event as event_mod
    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(raising_publish))

    # Configure the fake transport to emit an intra-turn event (triggers publish failure)
    async def _emit_one_event(on_event, session_id):
        from audiagentic.foundation.transports.acp import AcpEvent
        evt = AcpEvent(
            sequence=1, kind="thought",
            timestamp="2025-01-01T00:00:00Z", session_id=session_id,
            text=None, terminal=False, error=None,
            ext={"acp": {"raw_kind": "agent_thought_chunk"}},
        )
        result = on_event(evt)
        if result is not None:
            await result

    record = _open(runtime, tmp_path)
    transports[0].on_event_emitter = _emit_one_event  # transport created by open
    session_id = record["session-id"]

    # Prompt succeeds despite publish failure in on_event callback
    result = runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert result.stop_reason == "end_turn"

    runtime.close_session(tmp_path, session_id)


# ── RV680: turn deadline, protocol cancel, silence watchdog ─────────


def test_turn_deadline_fails_session(rig):
    """A turn that exceeds session-turn-timeout-seconds fails the session
    with TO-AGW-090 instead of blocking the worker forever."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, turn_timeout_seconds=0.2)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()  # never set — the turn hangs

    with pytest.raises(AudiaGenticError) as excinfo:
        runtime.prompt_in_session(tmp_path, session_id, "hang forever")
    assert excinfo.value.code == "TO-AGW-090"

    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "failed"
    assert stored["close-reason"] == "turn-timeout"
    assert runtime.live_session_ids() == []


def test_request_cancel_interrupts_running_turn(rig):
    """request_cancel() reaches an in-flight turn via the transport
    cancel_signal and the turn returns stop_reason 'cancelled'."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()  # block until cancelled

    results: list = []

    def _turn():
        results.append(
            runtime.prompt_in_session(
                tmp_path, session_id, "long turn", request_id="req_cancel_1"
            )
        )

    worker = threading.Thread(target=_turn)
    worker.start()
    assert _wait_for(lambda: transports[0].block_event is not None and worker.is_alive())
    time.sleep(0.05)  # let the turn reach the transport block loop
    assert runtime.request_cancel("req_cancel_1") is True
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert results and results[0].stop_reason == "cancelled"
    # The session survives a cancelled turn — only the turn was interrupted.
    assert runtime.live_session_ids() == [session_id]
    runtime.close_session(tmp_path, session_id)


def test_silence_watchdog_fails_silent_turn_as_policy_timeout(rig):
    """With an explicit silence bound, a turn producing no transport events
    hits a configured policy timeout and the reaper fails the session."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, turn_silence_timeout_seconds=5.0, turn_timeout_seconds=0)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()  # silent, endless turn

    def _turn():
        with pytest.raises(AudiaGenticError):
            runtime.prompt_in_session(tmp_path, session_id, "silent turn")

    worker = threading.Thread(target=_turn)
    worker.start()
    assert _wait_for(lambda: worker.is_alive())
    time.sleep(0.1)  # turn is now inside the transport block loop
    clock.now += 60.0  # exceed the 5s silence bound on the injected clock
    assert _wait_for(lambda: session_id not in runtime.live_session_ids(), timeout=5.0)
    # The reaper closed the transport; the aborted in-flight turn raises.
    worker.join(timeout=5.0)
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "failed"
    assert stored["close-reason"] == "turn-silence-timeout"


# AS34: stale persisted active session diagnostics.

def test_stale_persisted_session_lists_not_live_no_runtime_started(tmp_path, monkeypatch):
    """A persisted active session with no live runtime lists as not-live with a
    stale diagnostic flag, and listing does NOT start a new runtime."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    # No runtime — ensure by resetting the singleton.
    saved_runtime = getattr(sessions_module, "_SESSION_RUNTIME", None)
    try:
        sessions_module._SESSION_RUNTIME = None  # type: ignore[attr-defined]

        # Persisted active record — no live handle in this process
        record = session_store.build_session_record(agent_profile_id="profile-1")
        stale_id = record["session-id"]
        session_store.write_session_record(tmp_path, record)

        listed = api.list_llm_sessions(tmp_path)
        row = [s for s in listed if s["session-id"] == stale_id][0]
        assert row["live"] is False
        # A stale persisted active session should carry a diagnostic flag.
        assert row.get("runtime-state") == "stale-non-live"

        # The stored record must remain unchanged (no mutation of stale rows)
        stored = session_store.read_session_record(tmp_path, stale_id)
        assert stored["state"] == "active"

        # Listing did not start a runtime
        assert sessions_module.peek_session_runtime() is None
    finally:
        if saved_runtime is not None:
            sessions_module._SESSION_RUNTIME = saved_runtime  # type: ignore[attr-defined]


def test_live_session_lists_without_stale_flag(rig, monkeypatch):
    """A live active session from the runtime lists as live=True and does NOT
    carry a stale diagnostic flag."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    listed = api.list_llm_sessions(tmp_path)
    row = [s for s in listed if s["session-id"] == session_id][0]
    assert row["live"] is True
    # Live sessions must not carry a stale flag.
    assert row.get("runtime-state") != "stale-non-live"


def test_gateway_overview_active_count_excludes_stale(rig, monkeypatch):
    """gateway_overview counts only live sessions in active-count, not stale
    persisted active rows."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    # One live session from the runtime
    live_record = _open(runtime, tmp_path)

    # One stale persisted active session (no live handle)
    stale_record = session_store.build_session_record(agent_profile_id="profile-1")
    session_store.write_session_record(tmp_path, stale_record)

    overview = api.gateway_overview(tmp_path)
    assert overview["sessions"]["active-count"] == 1  # only the live one
    # The stale session should appear in the detail list but not count as active
    session_ids = [s["session-id"] for s in overview["sessions"]["sessions"]]
    assert live_record["session-id"] in session_ids
    assert stale_record["session-id"] in session_ids

    # Clean up
    runtime.close_session(tmp_path, live_record["session-id"])


def test_list_sessions_no_provider_ref_leak(rig, monkeypatch):
    """Public session rows must not leak provider-session-ref or full
    provider-ref-key; only the prefix is allowed (binding projection)."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    listed = api.list_llm_sessions(tmp_path)
    row = [s for s in listed if s["session-id"] == record["session-id"]][0]

    # repr of the entire listing must not contain provider-session-ref or
    # the full provider-ref-key hash (only the 12-char prefix is allowed).
    listing_repr = repr(listed)
    assert "provider-session-ref" not in listing_repr
    # The full key is 64 hex chars; if it leaked, we'd see >12 hex chars.
    full_key = record["binding"]["provider-ref-key"]
    assert full_key not in listing_repr

    # Only the prefix should be present
    binding_row = row.get("binding", {})
    assert "provider-ref-key-prefix" in binding_row
    assert len(binding_row["provider-ref-key-prefix"]) == 12


# AS35: close result redaction.


def test_api_close_live_session_result_is_redacted(rig, monkeypatch):
    """Live close returns public session shape: no provider-session-ref or full
    provider-ref-key in the close result, but useful fields are retained."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    closed = api.close_llm_session(tmp_path, session_id)
    assert closed["state"] == "closed"
    assert closed["close-reason"] == "client-request"
    assert closed["session-id"] == session_id
    assert closed["agent-profile-id"] == "profile-1"

    # Redaction: no provider-session-ref or full provider-ref-key in output
    close_repr = repr(closed)
    assert "provider-session-ref" not in close_repr
    full_key = record["binding"]["provider-ref-key"]
    assert full_key not in close_repr

    # Public binding projection is present with prefix
    pub_binding = closed.get("binding", {})
    assert "provider-ref-key-prefix" in pub_binding
    assert len(pub_binding["provider-ref-key-prefix"]) == 12


def test_api_close_durable_record_retains_protected_binding(rig, monkeypatch):
    """After close, the durable persisted session record still carries the
    protected binding internals for ownership/recovery (AS35 requirement 4)."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    original_ref = record["binding"]["provider-session-ref"]

    closed = api.close_llm_session(tmp_path, session_id)
    # Public result is redacted
    assert "provider-session-ref" not in repr(closed)

    # Durable record retains protected binding
    durable = session_store.read_session_record(tmp_path, session_id)
    assert durable["binding"]["provider-session-ref"] == original_ref
    assert durable["binding"]["provider-ref-key"]  # full key present


def test_api_close_idempotent_terminal_result_is_redacted(rig, monkeypatch):
    """Idempotent close of an already-terminal session returns a redacted
    public result (AS35 requirement 5 — idempotent path)."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    # Close first time
    api.close_llm_session(tmp_path, session_id)
    full_key = record["binding"]["provider-ref-key"]

    # Idempotent second close reads from durable store.
    again = api.close_llm_session(tmp_path, session_id)
    assert again["state"] == "closed"
    again_repr = repr(again)
    assert "provider-session-ref" not in again_repr
    assert full_key not in again_repr


def test_api_close_orphaned_stale_result_is_redacted(rig, monkeypatch):
    """Close of a stale non-live active session (orphaned by restart) returns
    a redacted public result with state=failed/close-reason=orphaned (AS35
    requirement 5 - stale non-live active path)."""
    from audiagentic.components.agents import agents_gateway_api as api
    from audiagentic.components.agents import agents_gateway_sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    # Build a fresh persisted active record (no live handle) to simulate orphan
    orphan_record = session_store.build_session_record(
        agent_profile_id="profile-1",
        provider_id="opencode",
        provider_session_ref="orphan-ref",
    )
    orphan_id = orphan_record["session-id"]
    full_key = orphan_record["binding"]["provider-ref-key"]
    session_store.write_session_record(tmp_path, orphan_record)

    closed = api.close_llm_session(tmp_path, orphan_id)
    assert closed["state"] == "failed"
    assert closed["close-reason"] == "orphaned"
    # Redacted public result
    close_repr = repr(closed)
    assert "provider-session-ref" not in close_repr
    assert full_key not in close_repr

    # Durable record still has protected binding for recovery
    durable = session_store.read_session_record(tmp_path, orphan_id)
    assert durable["binding"]["provider-session-ref"] == "orphan-ref"


def test_latest_turn_projection_excludes_native_topic(tmp_path: Path) -> None:
    """native-topic is not public; latest_turn_projection must not leak it."""
    import json

    from audiagentic.components.agents import agents_gateway_sessions_store as session_store
    from audiagentic.components.agents.agents_paths import gateway_session_timeline_path

    # Build a minimal session record so timeline path exists
    record = session_store.build_session_record(agent_profile_id="default")
    session_id = record["session-id"]
    session_store.write_session_record(tmp_path, record)

    # Write a turn timeline entry with native-topic (NDJSON format)
    timeline_path = gateway_session_timeline_path(tmp_path, session_id)
    entry = {
        "event": "session.turn.started",
        "state": "active",
        "timestamp": "2026-07-19T00:00:00Z",
        "attributes": {
            "request-id": "req_test",
            "native-topic": "provider.internal.secret-topic",
            "turn-count": 1,
        },
    }
    timeline_path.write_text(json.dumps(entry), encoding="utf-8")

    projected = session_store.latest_turn_projection(tmp_path, session_id, request_id="req_test")
    assert projected is not None
    assert projected["event"] == "session.turn.started"
    assert projected["turn-count"] == 1
    # native-topic must not leak
    assert "native-topic" not in projected
    assert "provider.internal.secret-topic" not in repr(projected)
