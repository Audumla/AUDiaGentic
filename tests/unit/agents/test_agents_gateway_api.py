"""Unit tests for agents_gateway_api — the full submit/status/wait/cancel/run
stack wired together (store + queue + dispatch), against a fake execute_provider
(AG11's own validation criteria)."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents import agents_gateway_api as gateway
from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.components.agents.agents_paths import gateway_idempotency_index_path
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.io import atomic_write_json


def _make_profile(project_root: Path, profile_id: str, provider_id: str, **params) -> None:
    create_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": "gpt-4o",
        "is_default": True,
        "params": params,
    })
    set_implementation_state(project_root, "providers", provider_id, ImplementationState(enabled=True))


def _result(data: dict) -> SimpleNamespace:
    return SimpleNamespace(result_data=data)


def test_submit_returns_immediately_for_long_running_request(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")
    hold = threading.Event()

    def slow_execute_provider(*, identity, execution_request, timeout_seconds):
        hold.wait(timeout=5)
        return _result({"provider-id": execution_request["provider-id"], "status": "ok", "model": "gpt-4o", "output": "done"})

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", slow_execute_provider)

    result = gateway.submit_llm_request(tmp_path, prompt_body="hi")
    assert result["request-id"].startswith("req_")
    assert result["state"] in ("queued", "running")  # returned without waiting for completion

    hold.set()
    gateway.wait_llm_request(tmp_path, result["request-id"], timeout_seconds=5)


def test_run_blocks_until_completion_and_returns_output(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        return _result({"provider-id": execution_request["provider-id"], "status": "ok", "model": "gpt-4o", "output": "the answer"})

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", fake_execute_provider)

    result = gateway.run_llm_request(tmp_path, prompt_body="hi")
    assert result["state"] == "completed"
    assert result["output"] == "the answer"


def test_active_component_profile_changes_execution_fingerprint(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        return _result({"provider-id": execution_request["provider-id"], "status": "ok", "model": "gpt-4o", "output": "done"})

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", fake_execute_provider)

    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "benchmark-a")
    first = gateway.run_llm_request(tmp_path, prompt_body="same prompt")
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "benchmark-b")
    second = gateway.run_llm_request(tmp_path, prompt_body="same prompt")

    assert first["context-fingerprint"] != second["context-fingerprint"]


def test_submit_replays_same_idempotency_key_without_second_enqueue(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")
    executions: list[str] = []
    hold = threading.Event()
    started = threading.Event()

    def slow_execute_provider(*, execution_request, **_kwargs):
        executions.append(execution_request["packet-data"]["request-id"])
        started.set()
        hold.wait(timeout=5)
        return _result({"provider-id": "local-openai", "status": "ok", "model": "gpt-4o", "output": "done"})

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", slow_execute_provider)
    metadata = {"idempotency_key": "opaque-client-key"}
    first = gateway.submit_llm_request(tmp_path, prompt_body="same", metadata=metadata)
    assert started.wait(timeout=2)
    # The index is advisory. A stale-but-valid intent digest must be repaired
    # from the durable record before this replay is allowed through.
    key_digest = store.hash_idempotency_key("opaque-client-key")
    atomic_write_json(gateway_idempotency_index_path(tmp_path, key_digest), {
        "key-digest": key_digest,
        "intent-digest": "0" * 64,
        "request-id": first["request-id"],
    })
    second = gateway.submit_llm_request(tmp_path, prompt_body="same", metadata=metadata)

    assert second["request-id"] == first["request-id"]
    assert len(executions) == 1
    persisted = gateway.get_llm_request(tmp_path, first["request-id"])
    assert "opaque-client-key" not in str(persisted)
    with pytest.raises(AudiaGenticError, match="CON-AGW-081"):
        gateway.submit_llm_request(
            tmp_path, prompt_body="different", metadata={"idempotency_key": "opaque-client-key"}
        )
    hold.set()


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"metadata": {"idempotency_key": 7}}, "idempotency_key"),
        ({"metadata": {"schema_version": "1"}}, "schema_version"),
        ({"timeout_seconds": "later"}, "timeout_seconds"),
    ],
)
def test_direct_submission_rejects_malformed_wire_values_before_resolution(
    tmp_path: Path, kwargs: dict, field: str
) -> None:
    with pytest.raises(AudiaGenticError) as exc:
        gateway.submit_llm_request(tmp_path, prompt_body="hello", **kwargs)
    assert exc.value.code == "VAL-AGW-082"
    assert exc.value.details["field"] == field


def test_wait_returns_timeout_status_for_still_running_request(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")
    hold = threading.Event()

    def slow_execute_provider(*, identity, execution_request, timeout_seconds):
        hold.wait(timeout=5)
        return _result({"provider-id": execution_request["provider-id"], "status": "ok", "model": "gpt-4o", "output": "done"})

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", slow_execute_provider)

    submitted = gateway.submit_llm_request(tmp_path, prompt_body="hi")
    result = gateway.wait_llm_request(tmp_path, submitted["request-id"], timeout_seconds=0.2)
    assert result["state"] == "running"

    hold.set()
    gateway.wait_llm_request(tmp_path, submitted["request-id"], timeout_seconds=5)


class _RecordingManager:
    def __init__(self):
        self.calls = {}

    def wait(self, project_root, request_id, timeout_seconds):
        self.calls["timeout"] = timeout_seconds
        return {"state": "running"}


def test_core_wait_honours_the_callers_timeout(tmp_path: Path, monkeypatch):
    """The 300s limit is an MCP TRANSPORT cap, applied at the MCP boundary.

    The core API must not impose it: the worker is a daemon thread in the
    caller's process, so capping here meant any task longer than the cap was
    abandoned mid-attempt when the caller returned and exited — the record
    stranded at 'running' forever. A supervisor owning a long implementation
    task must be able to wait for as long as the work takes (RV511).
    """
    manager = _RecordingManager()
    monkeypatch.setattr(gateway, "_QUEUE_MANAGER", manager)
    gateway.wait_llm_request(tmp_path, "req_x", timeout_seconds=10_000)
    assert manager.calls["timeout"] == 10_000


def test_core_wait_still_bounded_when_no_timeout_requested(tmp_path: Path, monkeypatch):
    """No requested timeout must not mean 'block forever'."""
    manager = _RecordingManager()
    monkeypatch.setattr(gateway, "_QUEUE_MANAGER", manager)
    gateway.wait_llm_request(tmp_path, "req_x")
    assert manager.calls["timeout"] == gateway.DEFAULT_BLOCKING_TIMEOUT_SECONDS


def test_cancel_queued_request_reaches_cancelled_state(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai", **{"max-concurrency": 1})
    hold = threading.Event()
    started = threading.Event()

    def slow_execute_provider(*, identity, execution_request, timeout_seconds):
        started.set()
        hold.wait(timeout=5)
        return _result({"provider-id": execution_request["provider-id"], "status": "ok", "model": "gpt-4o", "output": "done"})

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", slow_execute_provider)

    # occupy the only concurrency slot
    first = gateway.submit_llm_request(tmp_path, prompt_body="first")
    assert started.wait(timeout=2)

    second = gateway.submit_llm_request(tmp_path, prompt_body="second")
    assert second["state"] == "queued"

    cancelled = gateway.cancel_llm_request(tmp_path, second["request-id"])
    assert cancelled["state"] == "cancelled"

    hold.set()
    gateway.wait_llm_request(tmp_path, first["request-id"], timeout_seconds=5)


def test_list_llm_requests_most_recent_first_and_filterable(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        return _result({"provider-id": execution_request["provider-id"], "status": "ok", "model": "gpt-4o", "output": "done"})

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", fake_execute_provider)

    def failing_execute_provider(**_kwargs):
        from audiagentic.foundation.contracts.errors import AudiaGenticError
        raise AudiaGenticError(code="VAL-FAKE-002", kind="providers", message="bad")

    first = gateway.run_llm_request(tmp_path, prompt_body="first")
    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", failing_execute_provider)
    second = gateway.run_llm_request(tmp_path, prompt_body="second")

    all_requests = gateway.list_llm_requests(tmp_path)
    assert [r["request-id"] for r in all_requests] == [second["request-id"], first["request-id"]]

    failed_only = gateway.list_llm_requests(tmp_path, state="failed")
    assert [r["request-id"] for r in failed_only] == [second["request-id"]]

    limited = gateway.list_llm_requests(tmp_path, limit=1)
    assert len(limited) == 1
    assert limited[0]["request-id"] == second["request-id"]


def test_gateway_overview_reflects_persisted_state_across_restart(tmp_path: Path, monkeypatch):
    """A fresh GatewayQueueManager (simulating a process restart) still sees
    persisted request counts/failures through gateway_overview — unlike
    gateway_status(), which only reports in-memory queue depths (RV33)."""
    _make_profile(tmp_path, "default", "local-openai")

    def failing_execute_provider(**_kwargs):
        from audiagentic.foundation.contracts.errors import AudiaGenticError
        raise AudiaGenticError(code="VAL-FAKE-003", kind="providers", message="broke")

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", failing_execute_provider)
    gateway.run_llm_request(tmp_path, prompt_body="hi")

    from audiagentic.components.agents import agents_gateway_queue
    gateway._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()  # simulate restart

    overview = gateway.gateway_overview(tmp_path)
    assert overview["total_requests"] == 1
    assert overview["by_state"] == {"failed": 1}
    assert len(overview["recent_failures"]) == 1
    assert overview["queues"] == {}  # in-memory state is gone after "restart"
