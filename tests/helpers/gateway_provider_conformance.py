"""Reusable gateway conformance scenarios for every provider descriptor."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_api as gateway
from audiagentic.components.agents import agents_gateway_sessions as sessions_module
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.components.providers.contracts.provider_execution import (
    ProviderAcpLaunchResult,
    ProviderExecutionResult,
)
from audiagentic.components.providers.descriptors.registry import all_descriptors
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.transports import AcpLaunch
from tests.unit.agents.test_agents_gateway_sessions import (
    FakeAgentSessionTransport,
    _build_fake_prepared,
    _Clock,
)


def provider_ids() -> tuple[str, ...]:
    return tuple(sorted(all_descriptors()))


def reset_gateway_queue() -> None:
    """Reset between provider scenarios so each gets an empty in-memory queue."""
    from tests.helpers.gateway_queue_isolation import reset_gateway_queue as _reset

    _reset()


def enable_profile(
    project_root: Path,
    provider_id: str,
    *,
    profile_id: str = "default",
    max_concurrency: int = 1,
    queue_max_size: int | None = None,
) -> None:
    params: dict[str, Any] = {"max-concurrency": max_concurrency}
    if queue_max_size is not None:
        params["queue-max-size"] = queue_max_size
    create_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": f"{provider_id}-model",
        "is_default": profile_id == "default",
        "params": params,
    })
    set_implementation_state(
        project_root,
        "providers",
        provider_id,
        ImplementationState(enabled=True),
    )


def patch_gateway_provider_boundaries(monkeypatch: Any) -> None:
    monkeypatch.setattr(gateway, "_resolve_provider_isolation_tier", lambda _provider_id: "full-isolation")
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.get_provider_runtime_config_state",
        lambda _root, provider_id: {"provider-id": provider_id, "enabled": True, "config": {}},
    )


def assert_one_shot_state_matrix(project_root: Path, provider_id: str, monkeypatch: Any) -> None:
    reset_gateway_queue()
    enable_profile(project_root, provider_id, queue_max_size=1)
    patch_gateway_provider_boundaries(monkeypatch)
    hold = threading.Event()
    provider_started = threading.Event()

    def controlled_provider(*, identity, execution_request, timeout_seconds):
        prompt = execution_request["packet-data"]["prompt-body"]
        if "FAIL" in prompt:
            from audiagentic.foundation.contracts.errors import AudiaGenticError

            raise AudiaGenticError(
                code="EXT-FAKE-500",
                kind="providers",
                message="fake provider failed on command",
            )
        if "HOLD" in prompt:
            provider_started.set()
            hold.wait(timeout=5)
        return ProviderExecutionResult(
            provider_id=provider_id,
            model_id=f"{provider_id}-model",
            worker_id=identity.worker_id,
            attempt_epoch=identity.attempt_epoch,
            result_data={
                "provider-id": provider_id,
                "model": f"{provider_id}-model",
                "output": f"{provider_id}:ok:{prompt}",
            },
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        controlled_provider,
    )

    completed = gateway.run_execution_request(project_root, prompt_body="COMPLETE", timeout_seconds=5)
    assert completed["state"] == "completed"
    assert completed["provider-id"] == provider_id
    assert completed["output"] == f"{provider_id}:ok:COMPLETE"

    failed = gateway.run_execution_request(project_root, prompt_body="FAIL", timeout_seconds=5)
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "EXT-FAKE-500"
    assert failed["attempts"][-1]["provider-id"] == provider_id

    running = gateway.submit_execution_request(project_root, prompt_body="HOLD", mode="async")
    assert provider_started.wait(timeout=2)
    running_status = gateway.request_runtime_status(project_root, running["request-id"])
    assert running_status["queue-state"] == "running"
    assert running_status["profile-slot"] == "active"

    queued = gateway.submit_execution_request(project_root, prompt_body="QUEUED", mode="async")
    queued_status = gateway.request_runtime_status(project_root, queued["request-id"])
    assert queued_status["queue-state"] == "queued"
    assert queued_status["profile-slot"] == "pending"

    cancelled = gateway.cancel_execution_request(project_root, queued["request-id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["cancel-acknowledged-by"] == "queue-worker"

    still_queued = gateway.submit_execution_request(project_root, prompt_body="STILL-QUEUED", mode="async")
    assert still_queued["state"] == "queued"

    overflow = gateway.submit_execution_request(project_root, prompt_body="OVERFLOW", mode="async")
    assert overflow["state"] == "rejected"
    assert overflow["error"]["code"] == "VAL-AGW-025"

    hold.set()
    finished = gateway.wait_execution_request(project_root, running["request-id"], timeout_seconds=5)
    assert finished["state"] == "completed"


def assert_session_binding_open_flow(project_root: Path, provider_id: str, monkeypatch: Any) -> None:
    reset_gateway_queue()
    enable_profile(project_root, provider_id)
    patch_gateway_provider_boundaries(monkeypatch)
    transports: list[FakeAgentSessionTransport] = []

    def factory(project_root, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.provider_session_ref = f"{provider_id}-session-ref"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = sessions_module.SessionRuntime(
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
            model_id=f"{kwargs['provider_id']}-model",
            launch=AcpLaunch(f"{kwargs['provider_id']}-fake-agent"),
        ),
    )

    try:
        opened = gateway.run_execution_request(
            project_root,
            prompt_body="open session",
            session_keep_alive=True,
            timeout_seconds=5,
        )
        assert opened["state"] == "completed"
        assert opened["provider-id"] == provider_id
        assert "provider-session-ref" not in repr(opened.get("completion"))
        assert opened["completion"]["binding"]["provider-id"] == provider_id

        status = gateway.request_runtime_status(project_root, opened["request-id"])
        assert status["queue-state"] == "terminal"
        assert status["session"]["available"] is True
        assert "provider-session-ref" not in repr(status)

        listed = gateway.list_execution_sessions(project_root)
        assert listed[0]["binding"]["provider-id"] == provider_id
        assert "provider-session-ref" not in repr(listed)
    finally:
        runtime.shutdown()
