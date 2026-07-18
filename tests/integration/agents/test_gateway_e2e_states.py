from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from tests.unit.agents.test_agents_gateway_sessions import FakeTransport, _Clock

from audiagentic.components.agents import agents_gateway_api as gateway
from audiagentic.components.agents import agents_gateway_queue
from audiagentic.components.agents import agents_gateway_sessions as sessions_module
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.components.agents.agents_gateway_sessions import SessionRuntime
from audiagentic.components.providers.providers_api import (
    ProviderAcpLaunchResult,
    ProviderExecutionResult,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.transports import AcpLaunch


@pytest.fixture(autouse=True)
def _fresh_gateway_queue_manager():
    gateway._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()
    yield


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
    create_profile(project_root, {
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
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        controlled_provider,
    )

    completed = gateway.run_llm_request(tmp_path, prompt_body="COMPLETE", timeout_seconds=5)
    assert completed["state"] == "completed"
    assert completed["output"] == "ok:COMPLETE"

    failed = gateway.run_llm_request(tmp_path, prompt_body="FAIL", timeout_seconds=5)
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "EXT-FAKE-500"

    running = gateway.submit_llm_request(tmp_path, prompt_body="HOLD", mode="async")
    assert provider_started.wait(timeout=2)
    timed_out = gateway.wait_llm_request(tmp_path, running["request-id"], timeout_seconds=0.05)
    assert timed_out["state"] == "running"
    running_status = gateway.request_runtime_status(tmp_path, running["request-id"])
    assert running_status["queue-state"] == "running"
    assert running_status["profile-slot"] == "active"

    queued = gateway.submit_llm_request(tmp_path, prompt_body="QUEUED", mode="async")
    queued_status = gateway.request_runtime_status(tmp_path, queued["request-id"])
    assert queued_status["queue-state"] == "queued"
    assert queued_status["profile-slot"] == "pending"
    cancelled = gateway.cancel_llm_request(tmp_path, queued["request-id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["cancel-requested"] is True
    assert cancelled["cancel-acknowledged-by"] == "queue-worker"

    still_queued = gateway.submit_llm_request(tmp_path, prompt_body="STILL-QUEUED", mode="async")
    assert still_queued["state"] == "queued"
    overflow = gateway.submit_llm_request(tmp_path, prompt_body="OVERFLOW", mode="async")
    assert overflow["state"] == "rejected"
    assert overflow["error"]["code"] == "VAL-AGW-025"

    hold.set()
    finished_running = gateway.wait_llm_request(tmp_path, running["request-id"], timeout_seconds=5)
    assert finished_running["state"] == "completed"
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
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        slow_provider,
    )

    submitted = gateway.submit_llm_request(tmp_path, prompt_body="slow", mode="async")
    assert provider_started.wait(timeout=2)
    cancelled = gateway.cancel_llm_request(tmp_path, submitted["request-id"])

    assert cancelled["state"] == "running"
    assert cancelled["cancel-requested"] is True
    assert cancelled["cancel-acknowledged-at"] is None

    release_provider.set()
    result = gateway.wait_llm_request(tmp_path, submitted["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"
    assert result["cancel-requested"] is True
    assert result["output"] == "finished despite cancel"


def test_negative_submission_and_lookup_errors_are_explicit(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="RES-AGP-003"):
        gateway.submit_llm_request(tmp_path, prompt_body="no default profile")

    _make_profile(tmp_path, enabled=False)
    result = gateway.run_llm_request(tmp_path, prompt_body="provider disabled", timeout_seconds=5)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-AGW-031"

    with pytest.raises(AudiaGenticError):
        gateway.get_llm_request(tmp_path, "req_missing")


def test_session_states_open_turn_close_and_orphan_detection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _make_profile(tmp_path, provider_id="opencode", model_id="m1")
    transports: list[FakeTransport] = []

    def factory(launch, cwd):
        transport = FakeTransport(launch, cwd)
        transports.append(transport)
        return transport

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        transport_factory=factory,
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
        opened = gateway.run_llm_request(
            tmp_path,
            prompt_body="open session",
            session_keep_alive=True,
            session_idle_timeout_seconds=30,
            timeout_seconds=5,
        )
        assert opened["state"] == "completed", opened
        session_id = opened["session-id"]

        sessions = gateway.list_llm_sessions(tmp_path)
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

        continued = gateway.run_llm_request(
            tmp_path,
            prompt_body="continue session",
            session_id=session_id,
            timeout_seconds=5,
        )
        assert continued["state"] == "completed"
        assert continued["session-id"] == session_id
        assert transports[0].turns == ["open session", "continue session"]

        closed = gateway.close_llm_session(tmp_path, session_id)
        assert closed["state"] == "closed"
        assert gateway.list_llm_sessions(tmp_path)[0]["live"] is False
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
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        delayed_provider,
    )

    submitted = gateway.submit_llm_request(tmp_path, prompt_body="late", mode="async")
    assert started.wait(timeout=2)
    first_wait = gateway.wait_llm_request(tmp_path, submitted["request-id"], timeout_seconds=0.01)
    assert first_wait["state"] == "running"

    second_wait = gateway.wait_llm_request(tmp_path, submitted["request-id"], timeout_seconds=5)
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
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        fake_provider,
    )
    monkeypatch.setattr(
        sessions_module,
        "get_session_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("diagnostic started runtime")),
    )
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: None)

    completed = gateway.run_llm_request(tmp_path, prompt_body="secret prompt", timeout_seconds=5)
    runtime_status = gateway.request_runtime_status(tmp_path, completed["request-id"])

    assert runtime_status["queue-state"] == "terminal"
    assert runtime_status["session"] == {"available": False}
    assert "secret prompt" not in repr(runtime_status)
    assert "secret-ish output" not in repr(runtime_status)
    assert "provider-session-ref" not in repr(runtime_status)
