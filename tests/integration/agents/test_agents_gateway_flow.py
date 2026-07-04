"""Integration tests for the Agent LLM Gateway (AG07-AG13): full flows through
agents_gateway_api / agents_gateway_events against a fake provider adapter —
async submit -> wait -> completed, blocking run, event -> completed event, and
user-facing errors for a disabled provider / missing default profile.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from audiagentic.components.agents import agents_gateway_api as gateway
from audiagentic.components.agents import agents_gateway_queue
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import get_bus, reset_bus
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


@pytest.fixture(autouse=True)
def _fresh_gateway_queue_manager():
    # agents_gateway_api._QUEUE_MANAGER is a process-global singleton by design
    # (one per hosting process) — reset it per test so requests using the same
    # default profile id across tests don't share in-memory queue state.
    gateway._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()
    yield


def _make_profile(project_root: Path, profile_id: str, provider_id: str, *, default: bool = True, **params) -> None:
    create_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": "gpt-4o",
        "is_default": default,
        "params": params,
    })
    set_implementation_state(project_root, "providers", provider_id, ImplementationState(enabled=True))


def test_async_submit_wait_completed_flow(tmp_path: Path, monkeypatch) -> None:
    """submit (async, default) -> wait -> completed, using a fake provider adapter."""
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "the answer"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    submitted = gateway.submit_llm_request(tmp_path, prompt_body="what is 2+2?")
    assert submitted["state"] in ("queued", "running", "completed")

    result = gateway.wait_llm_request(tmp_path, submitted["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"
    assert result["output"] == "the answer"
    assert result["provider-id"] == "local-openai"


def test_blocking_run_returns_terminal_result(tmp_path: Path, monkeypatch) -> None:
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "blocking answer"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = gateway.run_llm_request(tmp_path, prompt_body="what is 2+2?")
    assert result["state"] == "completed"
    assert result["output"] == "blocking answer"


def test_event_triggered_request_reaches_completed_event(tmp_path: Path, monkeypatch) -> None:
    from audiagentic.components.agents import agents_gateway_events as events
    from audiagentic.foundation.event import event_bus as event_bus_mod

    # Restore the ORIGINAL bus afterwards — import-time observer subscriptions
    # (memory, ledger, providers) must survive this test module.
    saved_bus = event_bus_mod._bus_instance
    reset_bus()
    events._REGISTERED = False
    events.register()
    try:
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
            return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "event answer"}

        monkeypatch.setattr(
            "audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider
        )

        received = []
        done = threading.Event()

        def on_completed(event_type, payload, metadata):
            received.append(payload)
            done.set()

        get_bus().subscribe("agents.llm.completed", on_completed)
        get_bus().publish("agents.llm.gateway.requested", {
            "project-root": str(tmp_path),
            "prompt-body": "hello from an event",
            "source": "test-integration",
        })

        assert done.wait(timeout=5)
        assert received[0]["state"] == "completed"
    finally:
        events._REGISTERED = False
        event_bus_mod._bus_instance = saved_bus


def test_disabled_provider_produces_user_facing_error(tmp_path: Path, monkeypatch) -> None:
    """A request against a disabled provider must fail with a clear domain error,
    not an obscure adapter-level exception — even though execute_provider is
    never actually called (dispatch rejects before dispatch)."""
    create_profile(tmp_path, {
        "profile_id": "default", "provider_id": "local-openai", "model_id": "gpt-4o", "is_default": True,
    })
    # provider deliberately left disabled

    calls = {"count": 0}

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        calls["count"] += 1
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "should not run"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = gateway.run_llm_request(tmp_path, prompt_body="hi")
    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-AGW-031"
    assert calls["count"] == 0


def test_missing_default_profile_raises_user_facing_error(tmp_path: Path) -> None:
    """No profiles configured at all — submitting without an explicit
    agent-profile-id must raise a clear resolution error, not crash."""
    with pytest.raises(AudiaGenticError) as exc_info:
        gateway.submit_llm_request(tmp_path, prompt_body="hi")
    assert exc_info.value.code == "RES-AGP-003"
