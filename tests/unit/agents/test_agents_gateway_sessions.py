"""AS02/AS03 — SessionRuntime + session store tests (plan agent-sessions).

Fake transport (no subprocess) + injected clock + fast reap interval give
deterministic coverage of the lifecycle guarantees: open/turn/close, idle
and max-lifetime reaping, busy rejection, dead-child failure, shutdown.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_gateway_sessions import SessionRuntime
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

    async def open(self) -> str:
        self.opened = True
        self.alive = True
        return "prov-ses-1"

    def is_alive(self) -> bool:
        return self.alive and not self.closed

    async def prompt(self, prompt: str, **kwargs) -> AcpResult:
        if self.block_event is not None:
            import asyncio
            while not self.block_event.is_set():
                await asyncio.sleep(0.01)
        self.turns.append(prompt)
        return AcpResult(
            session_id="prov-ses-1",
            stop_reason="end_turn",
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

    def factory(launch, cwd):
        transport = FakeTransport(launch, cwd)
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
    assert record["provider-session-ref"] == "prov-ses-1"
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

    record = _open(runtime, tmp_path)
    listed = api.list_llm_sessions(tmp_path)
    assert [s["session-id"] for s in listed] == [record["session-id"]]
    assert listed[0]["live"] is True

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


def test_request_record_session_field_validation():
    from audiagentic.components.agents import agents_gateway_store as store

    with pytest.raises(AudiaGenticError, match="VAL-AGW-057"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_id="ses_1", session_keep_alive=True,
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-058"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_keep_alive=True, fallback_profile_ids=["other"],
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-059"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_idle_timeout_seconds=60,
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_max_lifetime_seconds=60,  # requires keep-alive
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_keep_alive=True, session_max_lifetime_seconds=-1,
        )
    record = store.build_record(
        agent_profile_id="p", prompt_body="x",
        session_keep_alive=True, session_idle_timeout_seconds=60,
        session_max_lifetime_seconds=0,  # 0 = no lifetime cap (RV513)
    )
    assert record["session-keep-alive"] is True
    assert record["session-idle-timeout-seconds"] == 60
    assert record["session-max-lifetime-seconds"] == 0
