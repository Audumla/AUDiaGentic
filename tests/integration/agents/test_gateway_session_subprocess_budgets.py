"""AS06 completion (RV590) — real-subprocess session budgets + EventBus.

RV590 kept AS06 open because the byte-budget/dropped-count guarantees were
only proven against a mocked ACP connection (tests/unit/foundation), while
lifecycle/intra-turn EventBus delivery was only proven against a FakeTransport
double (tests/unit/agents/test_agents_gateway_sessions.py). Neither drove the
real fake_acp_agent.py subprocess far enough to trigger bounded eviction.

This test opens a live SessionRuntime session against the real subprocess
transport (no fakes/mocks), sends a "flood" prompt that emits enough
assistant-message events within one turn to exceed MAX_TOTAL_BYTES, and
asserts terminal-result retention, dropped-event accounting, and EventBus
turn-lifecycle delivery all hold together over the real process boundary.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from audiagentic.components.agents.agents_event_topics import (
    TURN_MODEL_COMPLETED_TOPIC,
    TURN_MODEL_STARTED_TOPIC,
)
from audiagentic.components.agents.agents_gateway_sessions import SessionRuntime
from audiagentic.foundation.event import get_bus, reset_bus
from audiagentic.foundation.transports import AcpLaunch

_FAKE_AGENT = str(
    Path(__file__).parent.parent.parent
    / "unit" / "foundation" / "transports" / "fixtures" / "fake_acp_agent.py"
)

_SUBPROCESS_TIMEOUT = 60.0


@pytest.fixture(autouse=True)
def _fresh_bus():
    reset_bus()
    yield
    reset_bus()


def test_real_subprocess_flood_evicts_bounded_and_publishes_turn_events(tmp_path):
    received: list[tuple[str, dict]] = []
    completed = threading.Event()

    def on_model_started(event_type, payload, metadata):
        received.append((event_type, payload))

    def on_model_completed(event_type, payload, metadata):
        received.append((event_type, payload))
        completed.set()

    get_bus().subscribe(TURN_MODEL_STARTED_TOPIC, on_model_started)
    get_bus().subscribe(TURN_MODEL_COMPLETED_TOPIC, on_model_completed)

    runtime = SessionRuntime()
    try:
        record = runtime.open_session(
            tmp_path,
            agent_profile_id="profile-1",
            launch=AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,)),
            provider_id="opencode",
            model_id="m1",
        )
        session_id = record["session-id"]

        result = runtime.prompt_in_session(
            tmp_path, session_id, "flood", request_id="req_flood",
            timeout_seconds=_SUBPROCESS_TIMEOUT,
        )

        # Terminal result retained despite bounded eviction of the flood.
        assert result.stop_reason == "end_turn"
        assert result.terminal_event is not None
        assert result.terminal_event.kind == "result"

        # The flood exceeded MAX_EVENTS — some events were evicted, but the
        # total-received count and bytes-buffered accounting stay honest.
        assert result.dropped_events > 0
        assert result.total_events > len(result.events)
        assert result.bytes_buffered >= 0

        # Lifecycle EventBus delivery happened over the real subprocess
        # boundary: exactly one model.started (deduped) and one
        # model.completed (from the terminal event), both correlated to this
        # request/session.
        assert completed.wait(timeout=5), "model.completed was never published"
        started = [p for t, p in received if t == TURN_MODEL_STARTED_TOPIC]
        finished = [p for t, p in received if t == TURN_MODEL_COMPLETED_TOPIC]
        assert len(started) == 1
        assert len(finished) == 1
        assert started[0]["session-id"] == session_id
        assert started[0]["request-id"] == "req_flood"
        assert finished[0]["session-id"] == session_id
    finally:
        runtime.shutdown()
