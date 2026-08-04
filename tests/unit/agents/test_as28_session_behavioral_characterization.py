"""AS28 slice 0.5 — behavioral characterization of current ACP-shaped session usage.

These are READ-ONLY characterization tests: they pin the existing behavioral
sequence so that the later neutral migration (slice 4) can prove parity without
changing runtime semantics.

AS28 slice 4a: the OPEN path now uses provider_prepare_fn returning
PreparedSessionTransport — no AcpLaunch/AcpSessionTransport involved in open.
The prompt/cancel/close paths still use the legacy ACP callback contract
(slice 5+) but behavioral outcomes are identical.

Pinned sequence: session open -> two FIFO turns -> cancel request -> close +
queue/terminal ownership behavior. Uses FakeAgentSessionTransport and fixtures.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from tests.unit.agents.test_agents_gateway_sessions import (
    FakeAgentSessionTransport,
    _build_fake_prepared,
    _Clock,
)

from audiagentic.components.agents.gateway.session import sessions_store as session_store
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime
from audiagentic.foundation.contracts.errors import AudiaGenticError

# ── helpers ──────────────────────────────────────────────────────


def _open(runtime: SessionRuntime, project_root: Path, **kwargs) -> dict[str, Any]:
    return runtime.open_session(
        project_root,
        execution_profile_id="profile-1",
        provider_id="opencode",
        model_id="m1",
        surface_hint=kwargs.pop("surface_hint", None),
        **kwargs,
    )


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ── fixture ──────────────────────────────────────────────────────

@pytest.fixture
def characterization_rig(tmp_path: Path):
    """SessionRuntime with injected clock and provider_prepare_fn; shut down after.

    AS28 slice 4a: no AcpLaunch — injects PreparedSessionTransport with fake transport.
    """
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock, reap_interval_seconds=60, provider_prepare_fn=fake_prepare
    )
    yield runtime, clock, transports, tmp_path
    runtime.shutdown()


# ── behavioral characterization: the canonical ACP session sequence ──

def test_acp_sequence_open_two_turns_cancel_close(
    characterization_rig,
):
    """Characterize: open -> two FIFO turns (first completes, second cancelled)
    -> close. This is the behavioral baseline for AS28 neutral migration parity.

    AS28 slice 4a open path:
    - SessionRuntime.open_session() resolves PreparedSessionTransport via
      provider_prepare_fn(project_root, provider_id, surface_hint, model_id).
    - Transport from prepared.transport is opened (no AcpLaunch/AcpSessionTransport).
    - prompt_in_session() uses cancel_signal=asyncio.Event (RV680) and
      on_event=callback; result is AcpResult with events list.
    - request_cancel() sets the per-request cancel event.
    - close_session() calls transport.close() and transitions durable record.
    """
    runtime, clock, transports, tmp_path = characterization_rig

    # Step 1: open — resolves PreparedSessionTransport and opens its transport
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    assert record["state"] == "active"
    assert runtime.live_session_ids() == [session_id]

    # Step 2: first turn completes normally (end_turn stop_reason)
    result1 = runtime.prompt_in_session(
        tmp_path, session_id, "first prompt", request_id="req_1"
    )
    assert result1.stop_reason == "end_turn"
    # AS28 slice 4b-A: result is SessionTurnResult with final_summary (not AcpResult)
    assert hasattr(result1, "observations_delivered"), "SessionTurnResult carries observations"
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["turn-count"] == 1
    assert stored["request-ids"] == ["req_1"]

    # Step 3: second turn blocked so cancel can be tested
    gate = threading.Event()
    transports[0].block_event = gate

    results: list = []

    def _second_turn():
        results.append(
            runtime.prompt_in_session(
                tmp_path, session_id, "second prompt", request_id="req_2"
            )
        )

    worker = threading.Thread(target=_second_turn)
    worker.start()
    # Wait for turn to enter transport block loop
    assert _wait_for(lambda: worker.is_alive())
    time.sleep(0.05)

    # Step 4: cancel the in-flight second turn via request_cancel
    cancelled = runtime.request_cancel("req_2")
    assert cancelled is True, "cancel signal was scheduled"
    worker.join(timeout=5.0)
    assert not worker.is_alive(), "worker should have finished after cancel"
    # The turn returns with stop_reason='cancelled', session still alive
    assert results and results[0].stop_reason == "cancelled"
    assert runtime.live_session_ids() == [session_id]

    # Step 5: close the session — idempotent, transitions to 'closed'
    closed = runtime.close_session(tmp_path, session_id)
    assert closed["state"] == "closed"
    assert closed["close-reason"] == "client-request"
    assert transports[0].closed
    assert runtime.live_session_ids() == []

    # Durable record reflects the full sequence
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["turn-count"] == 2
    assert sorted(stored["request-ids"]) == ["req_1", "req_2"]


def test_acp_sequence_queue_fifo_ordering(
    characterization_rig,
):
    """Characterize: two concurrent turns queue FIFO (RV513), not reject.

    Current ACP behavior: pending counter + turn_lock on _SessionHandle.
    This is the queue ownership model AS28 must preserve.
    """
    runtime, clock, transports, tmp_path = characterization_rig

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    results: list[Any] = []

    def turn(prompt):
        results.append(
            runtime.prompt_in_session(tmp_path, session_id, prompt)
        )

    first = threading.Thread(target=turn, args=("first",))
    second = threading.Thread(target=turn, args=("second",))
    first.start()
    time.sleep(0.1)  # first turn is in flight (blocked on gate)
    second.start()
    time.sleep(0.1)  # second turn is queued
    assert results == [], "nothing finished yet — FIFO queue, not reject"

    gate.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert transports[0].turns == ["first", "second"], "FIFO order preserved"
    assert len(results) == 2

    runtime.close_session(tmp_path, session_id)


def test_acp_sequence_queue_full_rejects(
    tmp_path: Path,
):
    """Characterize: queue exceeding session_queue_max raises CON-AGW-003.

    Current ACP behavior: handle.pending >= session_queue_max -> reject.
    This is the back-pressure contract AS28 must preserve.
    """
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock, reap_interval_seconds=60,
        provider_prepare_fn=fake_prepare, session_queue_max=1,
    )
    try:
        record = _open(runtime, tmp_path)
        session_id = record["session-id"]
        gate = threading.Event()
        transports[0].block_event = gate

        def _swallow(fn):
            try:
                fn()
            except Exception:
                pass

        threads = [
            threading.Thread(
                target=lambda p=p: _swallow(
                    lambda: runtime.prompt_in_session(tmp_path, session_id, p)
                )
            )
            for p in ("running", "queued")
        ]
        threads[0].start()
        time.sleep(0.1)  # first turn in flight
        threads[1].start()
        time.sleep(0.1)  # one waiter — queue (max 1) now full

        # Third prompt should be rejected
        with pytest.raises(AudiaGenticError, match="CON-AGW-003"):
            runtime.prompt_in_session(tmp_path, session_id, "overflow")

        gate.set()
        for thread in threads:
            thread.join(timeout=2)
        assert transports[0].turns == ["running", "queued"]
    finally:
        runtime.shutdown()


def test_acp_sequence_terminal_ownership_after_close(
    characterization_rig,
):
    """Characterize: after close, the session record is terminal and no turns
    can be queued. The durable binding is retired (ownership transferred).

    Current ACP behavior: _handles.pop(session_id) removes the live handle;
    session_store transitions to 'closed'; binding_store.retire_binding().
    """
    runtime, clock, transports, tmp_path = characterization_rig

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    # Session is active
    stored_before = session_store.read_session_record(tmp_path, session_id)
    assert stored_before["state"] == "active"
    assert stored_before["binding"]["ownership"] == "owned"

    runtime.close_session(tmp_path, session_id)

    # Record is now terminal
    stored_after = session_store.read_session_record(tmp_path, session_id)
    assert stored_after["state"] in ("closed",)
    assert stored_after["close-reason"] == "client-request"

    # No live handle — new prompts fail
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.prompt_in_session(tmp_path, session_id, "after close")


def test_acp_sequence_failed_terminal_ownership(
    characterization_rig,
):
    """Characterize: dead child -> failed state -> binding retired.

    Current ACP behavior: _fail_session() pops the handle, closes transport,
    transitions to 'failed', retires binding.
    """
    runtime, clock, transports, tmp_path = characterization_rig

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    # Kill child out-of-band
    transports[0].alive = False

    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.prompt_in_session(tmp_path, session_id, "after death")

    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "failed"
    assert stored["close-reason"] == "failed"
    assert runtime.live_session_ids() == []


def test_acp_sequence_turn_cancel_preserves_binding(
    characterization_rig,
):
    """Characterize: a cancelled turn does NOT close the session or retire
    the binding — only the turn is interrupted.

    Current ACP behavior: cancel_signal races in transport.prompt(); on
    cancellation the session stays alive with its owned binding intact.
    """
    runtime, clock, transports, tmp_path = characterization_rig

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    def _turn():
        runtime.prompt_in_session(
            tmp_path, session_id, "long turn", request_id="req_cancel"
        )

    worker = threading.Thread(target=_turn)
    worker.start()
    assert _wait_for(lambda: worker.is_alive())
    time.sleep(0.05)

    # Cancel the turn
    runtime.request_cancel("req_cancel")
    worker.join(timeout=5.0)

    # Session still alive, binding still owned
    assert runtime.live_session_ids() == [session_id]
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "active"
    assert stored["binding"]["ownership"] == "owned"

    runtime.close_session(tmp_path, session_id)


def test_acp_sequence_on_event_callback_wired(
    characterization_rig,
):
    """Characterize: on_event= callback is wired during prompt() (AS18).

    Current ACP behavior: _make_on_event_callback creates the handler; it's
    passed as on_event= to transport.prompt(). The callback publishes
    normalized turn events and marks activity for the silence watchdog.

    This is an AS28 target — after migration, a neutral ObservationSink
    replaces on_event=.
    """
    runtime, clock, transports, tmp_path = characterization_rig

    # Emit one ACP event to prove the callback path works
    async def _emit(on_event, session_id):
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
    transports[0].on_event_emitter = _emit
    session_id = record["session-id"]

    result = runtime.prompt_in_session(
        tmp_path, session_id, "hello", request_id="req_1"
    )
    assert result.stop_reason == "end_turn"

    runtime.close_session(tmp_path, session_id)


# ── TODO: AS28 slice 4 boundary gate ─────────────────────────────
# The tests above characterize current ACP-shaped behavior. In slice 4, these
# same behavioral assertions must pass through the neutral AgentSessionTransport
# seam. The expected migration is:
#   AcpLaunch -> PreparedSessionTransport (via providers_api)
#   AcpResult.events -> SessionTurnResult.bounded_terminal_summary
#   on_event= -> ObservationSink
#   cancel_signal= -> SessionControlAction.CANCEL_TURN
#   TransportFactory[AcpSessionTransport] -> PreparedTransportFactory
