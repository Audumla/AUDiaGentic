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

    with pytest.raises(AudiaGenticError, match="VAL-AGW-057"):
        store.build_record(
            agent_profile_id="p", prompt_body="x",
            session_id="ses_1", session_keep_alive=True,
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


def test_silence_watchdog_fails_stalled_turn(rig):
    """With an explicit silence bound, a turn producing no transport events
    is proven stalled and the reaper fails the session."""
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
    assert stored["close-reason"] == "turn-stalled"
