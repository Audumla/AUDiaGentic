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

AS28 slice 4a moved transport resolution behind a ``provider_prepare_fn``
seam (``SessionRuntime.open_session()`` no longer accepts ``launch=`` —
see its docstring: "no AcpLaunch crosses this boundary"). To still drive a
real subprocess here, this test injects a ``provider_prepare_fn`` that
returns a ``PreparedSessionTransport`` wrapping a real, unopened
``AcpAgentSessionTransport`` (the same neutral ``AgentSessionTransport``
wrapper production provider adapters use — not the raw ``AcpSessionTransport``,
whose ``prompt()`` signature ``SessionRuntime`` does not call).
``SessionRuntime`` itself calls ``transport.open()``.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from tests.unit.agents.test_agents_gateway_sessions import _build_fake_prepared

from audiagentic.components.agents.gateway.event_topics import (
    TURN_MODEL_COMPLETED_TOPIC,
    TURN_MODEL_STARTED_TOPIC,
)
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime
from audiagentic.foundation.event import get_bus, reset_bus
from audiagentic.foundation.transports import AcpLaunch
from audiagentic.foundation.transports.acp import AcpAgentSessionTransport

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

    def prepare_real_subprocess(project_root, *, provider_id, surface_hint, model_id=None, **_kwargs):
        transport = AcpAgentSessionTransport(
            AcpLaunch(executable=sys.executable, args=(_FAKE_AGENT,)),
            cwd=project_root,
        )
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(provider_prepare_fn=prepare_real_subprocess)
    try:
        record = runtime.open_session(
            tmp_path,
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
        )
        session_id = record["session-id"]

        result = runtime.prompt_in_session(
            tmp_path, session_id, "flood", request_id="req_flood",
            timeout_seconds=_SUBPROCESS_TIMEOUT,
        )

        # Terminal result retained despite bounded eviction of the flood.
        # AS21 bounds SessionTurnResult to scalars only (no raw events/bytes
        # on the result — see its docstring); output delivery is the
        # observation sink's job, asserted via the EventBus below.
        assert result.stop_reason == "end_turn"
        assert result.error_code is None
        assert result.final_summary is not None

        # The flood exceeded MAX_EVENTS — some observations were evicted,
        # but delivery accounting stays honest: some got through, some didn't.
        assert result.observations_delivered > 0
        assert result.dropped_observations > 0

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
