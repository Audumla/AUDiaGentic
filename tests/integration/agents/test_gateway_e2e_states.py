from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from tests.unit.agents.test_agents_gateway_sessions import (
    FakeAgentSessionTransport,
    _build_fake_prepared,
    _Clock,
)

from audiagentic.components.agents.gateway import api as gateway
from audiagentic.components.agents.gateway.session import sessions as sessions_module
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime
from audiagentic.components.agents.models.execution_profile_api import (
    create_execution_profile,
)
from audiagentic.components.providers.providers_api import (
    ProviderAcpLaunchResult,
    ProviderExecutionResult,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.transports import AcpLaunch
from audiagentic.foundation.transports.agent_session import SessionTurnResult

pytestmark = pytest.mark.no_parallel


def _make_profile(
    project_root: Path,
    *,
    profile_id: str = "default",
    provider_id: str = "local-openai",
    model_id: str = "gpt-4o",
    enabled: bool = True,
    max_concurrency: int = 1,
    queue_max_size: int | None = None,
) -> None:
    params = {"max-concurrency": max_concurrency}
    if queue_max_size is not None:
        params["queue-max-size"] = queue_max_size
    create_execution_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": model_id,
        "is_default": profile_id == "default",
        "params": params,
    })
    set_implementation_state(
        project_root,
        "providers",
        provider_id,
        ImplementationState(enabled=enabled),
    )


def test_request_state_matrix_completed_failed_timeout_cancelled_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path, queue_max_size=1)
    hold = threading.Event()
    provider_started = threading.Event()

    def controlled_provider(*, identity, execution_request, timeout_seconds):
        prompt = execution_request["packet-data"]["prompt-body"]
        if "FAIL" in prompt:
            raise AudiaGenticError(
                code="EXT-FAKE-500",
                kind="providers",
                message="fake provider failed on command",
            )
        if "HOLD" in prompt:
            provider_started.set()
            hold.wait(timeout=5)
        return ProviderExecutionResult(
            provider_id="local-openai",
            model_id="gpt-4o",
            worker_id=identity.worker_id,
            attempt_epoch=identity.attempt_epoch,
            result_data={
                "provider-id": "local-openai",
                "model": "gpt-4o",
                "output": f"ok:{prompt}",
            },
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        controlled_provider,
    )

    completed = gateway.run_execution_request(tmp_path, prompt_body="COMPLETE", timeout_seconds=5)
    assert completed["state"] == "completed"
    assert completed["output"] == "ok:COMPLETE"

    failed = gateway.run_execution_request(tmp_path, prompt_body="FAIL", timeout_seconds=5)
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "EXT-FAKE-500"

    running = gateway.submit_execution_request(tmp_path, prompt_body="HOLD", mode="async")
    assert provider_started.wait(timeout=2)
    timed_out = gateway.wait_execution_request(tmp_path, running["request-id"], timeout_seconds=0.05)
    assert timed_out["state"] == "running"
    running_status = gateway.request_runtime_status(tmp_path, running["request-id"])
    assert running_status["queue-state"] == "running"
    assert running_status["profile-slot"] == "active"

    queued = gateway.submit_execution_request(tmp_path, prompt_body="QUEUED", mode="async")
    queued_status = gateway.request_runtime_status(tmp_path, queued["request-id"])
    assert queued_status["queue-state"] == "queued"
    assert queued_status["profile-slot"] == "pending"
    cancelled = gateway.cancel_execution_request(tmp_path, queued["request-id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["cancel-requested"] is True
    assert cancelled["cancel-acknowledged-by"] == "queue-worker"

    still_queued = gateway.submit_execution_request(tmp_path, prompt_body="STILL-QUEUED", mode="async")
    assert still_queued["state"] == "queued"
    overflow = gateway.submit_execution_request(tmp_path, prompt_body="OVERFLOW", mode="async")
    assert overflow["state"] == "rejected"
    assert overflow["error"]["code"] == "VAL-AGW-025"

    hold.set()
    finished_running = gateway.wait_execution_request(tmp_path, running["request-id"], timeout_seconds=5)
    assert finished_running["state"] == "completed"
    finished_queued = gateway.wait_execution_request(
        tmp_path, still_queued["request-id"], timeout_seconds=5
    )
    assert finished_queued["state"] == "completed"
    terminal_status = gateway.request_runtime_status(tmp_path, running["request-id"])
    assert terminal_status["queue-state"] == "terminal"
    assert terminal_status["profile-slot"] is None

    overview = gateway.gateway_overview(tmp_path)
    assert overview["by_state"]["completed"] == 3
    assert overview["by_state"]["failed"] == 1
    assert overview["by_state"]["cancelled"] == 1
    assert overview["by_state"]["rejected"] == 1


def test_running_cancel_is_detected_but_not_fabricated_as_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path)
    provider_started = threading.Event()
    release_provider = threading.Event()

    def slow_provider(*, identity, execution_request, timeout_seconds):
        provider_started.set()
        release_provider.wait(timeout=5)
        return ProviderExecutionResult(
            provider_id="local-openai",
            model_id="gpt-4o",
            worker_id=identity.worker_id,
            attempt_epoch=identity.attempt_epoch,
            result_data={
                "provider-id": "local-openai",
                "model": "gpt-4o",
                "output": "finished despite cancel",
            },
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        slow_provider,
    )

    submitted = gateway.submit_execution_request(tmp_path, prompt_body="slow", mode="async")
    assert provider_started.wait(timeout=2)
    cancelled = gateway.cancel_execution_request(tmp_path, submitted["request-id"])

    assert cancelled["state"] == "running"
    assert cancelled["cancel-requested"] is True
    assert cancelled["cancel-acknowledged-at"] is None

    release_provider.set()
    result = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"
    assert result["cancel-requested"] is True
    assert result["output"] == "finished despite cancel"


def test_negative_submission_and_lookup_errors_are_explicit(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="RES-EXP-003"):
        gateway.submit_execution_request(tmp_path, prompt_body="no default profile")

    _make_profile(tmp_path, enabled=False)
    result = gateway.run_execution_request(tmp_path, prompt_body="provider disabled", timeout_seconds=5)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-AGW-031"

    with pytest.raises(AudiaGenticError):
        gateway.get_execution_request(tmp_path, "req_missing")


def test_session_states_open_turn_close_and_orphan_detection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        opened = gateway.run_execution_request(
            tmp_path,
            prompt_body="open session",
            session_keep_alive=True,
            session_idle_timeout_seconds=30,
            timeout_seconds=5,
        )
        assert opened["state"] == "completed", opened
        session_id = opened["session-id"]

        sessions = gateway.list_execution_sessions(tmp_path)
        assert [(row["session-id"], row["state"], row["live"]) for row in sessions] == [
            (session_id, "active", True)
        ]
        assert transports[0].turns == ["open session"]
        session_status = gateway.request_runtime_status(tmp_path, opened["request-id"])
        assert session_status["queue-state"] == "terminal"
        assert session_status["session-id"] == session_id
        assert session_status["session"]["available"] is True
        assert session_status["session"]["pending-turns"] == 0
        assert "provider-session-ref" not in session_status["session"]

        continued = gateway.run_execution_request(
            tmp_path,
            prompt_body="continue session",
            session_id=session_id,
            timeout_seconds=5,
        )
        assert continued["state"] == "completed"
        assert continued["session-id"] == session_id
        assert transports[0].turns == ["open session", "continue session"]

        closed = gateway.close_execution_session(tmp_path, session_id)
        assert closed["state"] == "closed"
        assert gateway.list_execution_sessions(tmp_path)[0]["live"] is False
    finally:
        runtime.shutdown()


def test_continued_session_explicit_false_closes_after_turn_if_quiescent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Continuing a session with session_keep_alive=False explicitly closes
    it after the turn if quiescent."""
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        opened = gateway.run_execution_request(
            tmp_path,
            prompt_body="open session",
            session_keep_alive=True,
            timeout_seconds=5,
        )
        assert opened["state"] == "completed"
        session_id = opened["session-id"]

        # Continue with explicit keep_alive=False — should close after turn
        continued = gateway.run_execution_request(
            tmp_path,
            prompt_body="one-shot continue",
            session_id=session_id,
            session_keep_alive=False,
            timeout_seconds=5,
        )
        assert continued["state"] == "completed"
        assert continued["session-id"] == session_id

        # Session should be closed (not orphaned/failed) by post-turn close
        stored = gateway.list_execution_sessions(tmp_path)
        row = [s for s in stored if s["session-id"] == session_id][0]
        assert row["state"] == "closed"
        assert row["live"] is False
    finally:
        runtime.shutdown()


def test_continued_session_explicit_true_keeps_live_after_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Continuing a session with session_keep_alive=True keeps it live after
    the turn and allows bounds updates."""
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        opened = gateway.run_execution_request(
            tmp_path,
            prompt_body="open session",
            session_keep_alive=True,
            timeout_seconds=5,
        )
        assert opened["state"] == "completed"
        session_id = opened["session-id"]

        # Continue with explicit keep_alive=True — should stay live
        continued = gateway.run_execution_request(
            tmp_path,
            prompt_body="continue keeping alive",
            session_id=session_id,
            session_keep_alive=True,
            timeout_seconds=5,
        )
        assert continued["state"] == "completed"
        assert continued["session-id"] == session_id

        # Session should still be live
        stored = gateway.list_execution_sessions(tmp_path)
        row = [s for s in stored if s["session-id"] == session_id][0]
        assert row["live"] is True
        assert row["state"] == "active"

        # Can close it normally
        closed = gateway.close_execution_session(tmp_path, session_id)
        assert closed["state"] == "closed"
    finally:
        runtime.shutdown()


def test_wait_does_not_mask_terminal_state_after_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path)
    started = threading.Event()

    def delayed_provider(*, identity, execution_request, timeout_seconds):
        started.set()
        time.sleep(0.15)
        return ProviderExecutionResult(
            provider_id="local-openai",
            model_id="gpt-4o",
            worker_id=identity.worker_id,
            attempt_epoch=identity.attempt_epoch,
            result_data={
                "provider-id": "local-openai",
                "model": "gpt-4o",
                "output": "late success",
            },
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        delayed_provider,
    )

    submitted = gateway.submit_execution_request(tmp_path, prompt_body="late", mode="async")
    assert started.wait(timeout=2)
    first_wait = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=0.01)
    assert first_wait["state"] == "running"

    second_wait = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)
    assert second_wait["state"] == "completed"
    assert second_wait["output"] == "late success"


def test_request_runtime_status_is_redacted_and_does_not_start_session_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path)

    def fake_provider(*, identity, execution_request, timeout_seconds):
        return ProviderExecutionResult(
            provider_id="local-openai",
            model_id="gpt-4o",
            worker_id=identity.worker_id,
            attempt_epoch=identity.attempt_epoch,
            result_data={
                "provider-id": "local-openai",
                "model": "gpt-4o",
                "output": "secret-ish output that belongs on status, not diagnostics",
            },
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_provider,
    )
    monkeypatch.setattr(
        sessions_module,
        "get_session_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("diagnostic started runtime")),
    )
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: None)

    completed = gateway.run_execution_request(tmp_path, prompt_body="secret prompt", timeout_seconds=5)
    runtime_status = gateway.request_runtime_status(tmp_path, completed["request-id"])

    assert runtime_status["queue-state"] == "terminal"
    assert runtime_status["session"] == {"available": False}
    assert "secret prompt" not in repr(runtime_status)
    assert "secret-ish output" not in repr(runtime_status)
    assert "provider-session-ref" not in repr(runtime_status)


def test_request_runtime_status_projects_latest_session_turn_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    gate = threading.Event()
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.block_event = gate
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        submitted = gateway.submit_execution_request(
            tmp_path,
            prompt_body="long architecture review",
            mode="async",
            session_keep_alive=True,
            timeout_seconds=5,
        )

        deadline = time.time() + 2
        status = {}
        while time.time() < deadline:
            status = gateway.request_runtime_status(tmp_path, submitted["request-id"])
            latest = status.get("session", {}).get("latest-turn-event")
            if latest and latest.get("event") == "session.turn.started":
                break
            time.sleep(0.02)

        latest = status["session"]["latest-turn-event"]
        assert latest["event"] == "session.turn.started"
        assert latest["request-id"] == submitted["request-id"]
        assert "long architecture review" not in repr(status)
        assert "provider-session-ref" not in repr(status)

        gate.set()
        finished = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)
        assert finished["state"] == "completed"
    finally:
        gate.set()
        runtime.shutdown()


def test_cancelled_session_turn_preserves_bounded_result_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    started = threading.Event()

    class OutputOnCancelTransport(FakeAgentSessionTransport):
        async def prompt(self, prompt, sink=None, **kwargs) -> SessionTurnResult:
            cancel_signal = prompt.cancel_token
            started.set()
            while cancel_signal is None or not cancel_signal.is_set():
                import asyncio

                await asyncio.sleep(0.01)
            self.turns.append(prompt.body)
            return SessionTurnResult(
                turn_id=prompt.turn_id,
                stop_reason="cancelled",
                observations_delivered=2,
                dropped_observations=0,
                final_summary="partial review finding",
            )

    transports: list[OutputOnCancelTransport] = []

    def factory(project_root, **kwargs):
        transport = OutputOnCancelTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        submitted = gateway.submit_execution_request(
            tmp_path,
            prompt_body="cancel after output",
            mode="async",
            session_keep_alive=True,
            timeout_seconds=5,
        )
        assert started.wait(timeout=2)
        cancelled = gateway.cancel_execution_request(tmp_path, submitted["request-id"])
        assert cancelled["cancel-requested"] is True
        finished = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)
        assert finished["state"] == "cancelled"
        assert finished["output"] == "partial review finding"
        assert finished["completion"]["stop-reason"] == "cancelled"
        assert finished["completion"]["total-events"] == 2
        assert "provider-session-ref" not in repr(finished)
    finally:
        runtime.shutdown()


# AS33: capability projection tests.

def test_as33_capabilities_absent_when_no_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """AS33: capabilities key is absent when session record has no captured snapshot."""
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        completed = gateway.run_execution_request(
            tmp_path,
            prompt_body="open session",
            session_keep_alive=True,
            session_idle_timeout_seconds=30,
            timeout_seconds=5,
        )
        assert completed["state"] == "completed"
        runtime_status = gateway.request_runtime_status(tmp_path, completed["request-id"])
        assert "capabilities" not in runtime_status
    finally:
        runtime.shutdown()


def test_as33_capabilities_exposed_from_explicit_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """AS33: explicit capability-snapshot on session record is projected as capabilities."""
    import json

    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        completed = gateway.run_execution_request(
            tmp_path,
            prompt_body="open session",
            session_keep_alive=True,
            session_idle_timeout_seconds=30,
            timeout_seconds=5,
        )
        assert completed["state"] == "completed"
        session_id = completed["session-id"]

        # Inject capability-snapshot into raw JSON (bypassing schema validation).
        from audiagentic.components.agents.agents_paths import gateway_session_path

        record_path = gateway_session_path(tmp_path, session_id)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["capability-snapshot"] = {
            "surface-id": "acp-session",
            "surface-version": "1.0",
            "declared-controls": ["cancel", "observe"],
            "observation-mechanism": "polling",
            "observation-source": "gateway-diagnostic",
            "supported-statuses": ["active", "idle", "closed"],
            "evidence-tier": "resolved",
        }
        record_path.write_text(json.dumps(record), encoding="utf-8")

        runtime_status = gateway.request_runtime_status(tmp_path, completed["request-id"])
        capabilities = runtime_status.get("capabilities")
        assert capabilities is not None
        assert capabilities["surface-id"] == "acp-session"
        assert capabilities["surface-version"] == "1.0"
        assert "declared-controls" in capabilities
        assert capabilities["observation-mechanism"] == "polling"

        # Clean up injected field before shutdown so schema validation passes.
        record.pop("capability-snapshot", None)
        record_path.write_text(json.dumps(record), encoding="utf-8")
    finally:
        runtime.shutdown()


def test_as33_capabilities_redacts_unsafe_fields(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """AS33: unsafe fields (provider-session-ref, raw-payload, prompt, etc.) are dropped."""
    import json

    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        completed = gateway.run_execution_request(
            tmp_path,
            prompt_body="open session",
            session_keep_alive=True,
            session_idle_timeout_seconds=30,
            timeout_seconds=5,
        )
        assert completed["state"] == "completed"
        session_id = completed["session-id"]

        from audiagentic.components.agents.agents_paths import gateway_session_path

        record_path = gateway_session_path(tmp_path, session_id)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["capability-snapshot"] = {
            "surface-id": "acp-session",
            "provider-session-ref": "secret-provider-ref-12345",
            "raw-payload": {"some": "raw data"},
            "prompt": "the actual prompt text",
            "output": "the actual output text",
            "tool-arguments": {"arg": "value"},
            "native-ref": "native-123",
            "evidence-tier": "resolved",
        }
        record_path.write_text(json.dumps(record), encoding="utf-8")

        runtime_status = gateway.request_runtime_status(tmp_path, completed["request-id"])
        capabilities = runtime_status.get("capabilities")
        assert capabilities is not None
        # Safe field present
        assert capabilities["surface-id"] == "acp-session"
        assert capabilities["evidence-tier"] == "resolved"
        # Unsafe fields dropped
        for unsafe_key in (
            "provider-session-ref",
            "raw-payload",
            "prompt",
            "output",
            "tool-arguments",
            "native-ref",
        ):
            assert unsafe_key not in capabilities, f"{unsafe_key} leaked into capabilities"

        # Also verify no raw prompt/output/provider refs in the full runtime_status
        status_repr = repr(runtime_status)
        assert "secret-provider-ref-12345" not in status_repr
        assert "the actual prompt text" not in status_repr

        # Clean up injected field before shutdown so schema validation passes.
        record.pop("capability-snapshot", None)
        record_path.write_text(json.dumps(record), encoding="utf-8")
    finally:
        runtime.shutdown()


def test_as33_terminal_diagnostics_do_not_start_session_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """AS33: request_runtime_status does not start session runtime for terminal requests."""
    _make_profile(tmp_path)

    def fake_provider(*, identity, execution_request, timeout_seconds):
        return ProviderExecutionResult(
            provider_id="local-openai",
            model_id="gpt-4o",
            worker_id=identity.worker_id,
            attempt_epoch=identity.attempt_epoch,
            result_data={
                "provider-id": "local-openai",
                "model": "gpt-4o",
                "output": "done",
            },
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_provider,
    )
    monkeypatch.setattr(
        sessions_module,
        "get_session_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("diagnostic started runtime")),
    )
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: None)

    completed = gateway.run_execution_request(tmp_path, prompt_body="test", timeout_seconds=5)
    assert completed["state"] == "completed"
    # This should not raise: peek_session_runtime returns None for terminal.
    runtime_status = gateway.request_runtime_status(tmp_path, completed["request-id"])
    assert runtime_status["queue-state"] == "terminal"
    assert "capabilities" not in runtime_status  # no session, no snapshot


def test_running_session_request_has_latest_turn_event_but_no_output_yet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """RV735 production symptom: while an async keep-alive session request is
    still running, get_execution_request has no output but request_runtime_status
    exposes session.latest-turn-event for that same request. No prompt text,
    provider-session-ref, full provider-ref-key, or output leaks."""
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    gate = threading.Event()
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.block_event = gate
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=factory,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.prepare_provider_acp_launch",
        lambda root, **kwargs: ProviderAcpLaunchResult(
            provider_id=kwargs["provider_id"],
            model_id="m1",
            launch=AcpLaunch("fake-acp-agent"),
        ),
    )

    try:
        submitted = gateway.submit_execution_request(
            tmp_path,
            prompt_body="secret architecture review prompt",
            mode="async",
            session_keep_alive=True,
            timeout_seconds=5,
        )
        assert submitted["state"] == "queued"
        request_id = submitted["request-id"]

        status = {}
        latest = None
        deadline = time.time() + 5
        while time.time() < deadline:
            status = gateway.request_runtime_status(tmp_path, request_id)
            latest = status.get("session", {}).get("latest-turn-event")
            if latest and latest.get("event") == "session.turn.started":
                break
            time.sleep(0.02)

        assert latest is not None, f"timeout waiting for session.turn.started: {status}"
        assert latest["event"] == "session.turn.started"
        assert latest["request-id"] == request_id

        # The production symptom: public status has no output yet, but runtime
        # status shows active turn evidence.
        public_status = gateway.get_execution_request(tmp_path, request_id)
        assert public_status["output"] is None, "output should be None while running"

        # No prompt text leak in runtime status
        status_repr = repr(status)
        assert "secret architecture review prompt" not in status_repr

        # No provider-session-ref leak in runtime status
        assert "provider-session-ref" not in status_repr

        # No full provider-ref-key leak. The public binding may expose the
        # prefix, so assert against the actual protected full key.
        from audiagentic.components.agents.gateway.session import sessions_store as session_store

        session_id = status["session-id"]
        durable_session = session_store.read_session_record(tmp_path, session_id)
        full_key = durable_session["binding"]["provider-ref-key"]
        assert full_key not in status_repr

        gate.set()
        finished = gateway.wait_execution_request(tmp_path, request_id, timeout_seconds=5)
        assert finished["state"] == "completed"
    finally:
        gate.set()
        runtime.shutdown()
