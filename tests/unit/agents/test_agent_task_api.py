"""Unit tests for AgentTaskFactory and AgentTask (AS63 Phase 1 / RV891).

Uses the real gateway machinery end-to-end (like test_agents_gateway_api.py)
rather than mocks, so these tests prove AgentTaskFactory is a genuine
consumer of resolve_agent_definition -- the gap flagged before this item
started: nothing in `src` called it except tests.
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.models.agent_definition_api import (
    create_agent_definition,
)
from audiagentic.components.agents.models.agent_task_api import (
    AgentTask,
    AgentTaskFactory,
)
from audiagentic.components.agents.models.execution_profile_api import (
    create_execution_profile,
)
from audiagentic.components.agents.models.role_api import create_role
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


def _setup_agent(tmp_path: Path, *, agent_id: str = "reviewer-agent") -> None:
    (tmp_path / ".audiagentic").mkdir(exist_ok=True)
    create_execution_profile(
        tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]}
    )
    set_implementation_state(tmp_path, "providers", "local-openai", ImplementationState(enabled=True))
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})
    create_agent_definition(
        tmp_path,
        {
            "agent_id": agent_id,
            "name": "Reviewer Agent",
            "execution_profile_id": "fast",
            "role_id": "reviewer",
        },
    )


def _block_dispatch(monkeypatch) -> tuple[threading.Event, threading.Event]:
    """Hold every dispatched request in 'running' indefinitely, so status
    reads taken moments apart are deterministically stable -- the same
    pattern test_agents_gateway_api.py's own concurrency tests use, rather
    than racing a real provider dispatch."""
    started = threading.Event()
    hold = threading.Event()

    def slow_execute_provider(*, identity, execution_request, timeout_seconds):
        started.set()
        hold.wait(timeout=10)
        return SimpleNamespace(
            result_data={
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o-mini",
                "output": "done",
            }
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        slow_execute_provider,
    )
    return started, hold


# ---------------------------------------------------------------------------
# AgentTaskFactory.submit -- agent_id primary path
# ---------------------------------------------------------------------------

def test_submit_resolves_agent_and_returns_agent_task(tmp_path: Path, monkeypatch):
    _setup_agent(tmp_path)
    started, hold = _block_dispatch(monkeypatch)
    factory = AgentTaskFactory(tmp_path)

    task = factory.submit("reviewer-agent", prompt_body="hi")
    assert started.wait(timeout=2)

    assert isinstance(task, AgentTask)
    assert task.request_id
    status = task.status()
    assert status["execution-profile-id"] == "fast"
    hold.set()


def test_submit_unknown_agent_raises_res_agd_001(tmp_path: Path):
    (tmp_path / ".audiagentic").mkdir()
    factory = AgentTaskFactory(tmp_path)

    with pytest.raises(AudiaGenticError) as exc_info:
        factory.submit("missing-agent", prompt_body="hi")
    assert exc_info.value.code == "RES-AGD-001"


def test_submit_forwards_kwargs_to_gateway(tmp_path: Path):
    """Extra kwargs reach submit_execution_request's own validation unchanged
    -- AgentTaskFactory does not narrow or re-validate the existing capability
    set. Proven via a rejection (VAL-AGW-082, the SubmissionEnvelope-stage
    check) rather than a passthrough field, since most gateway kwargs are
    session-lifecycle-sensitive or excluded from the public status
    projection's allowlist."""
    _setup_agent(tmp_path)
    factory = AgentTaskFactory(tmp_path)

    with pytest.raises(AudiaGenticError) as exc_info:
        factory.submit("reviewer-agent", prompt_body="hi", timeout_seconds=-1)
    assert exc_info.value.code == "VAL-AGW-082"


# ---------------------------------------------------------------------------
# AgentTaskFactory.submit_raw -- explicit lower-level surface
# ---------------------------------------------------------------------------

def test_submit_raw_bypasses_agent_definition(tmp_path: Path, monkeypatch):
    (tmp_path / ".audiagentic").mkdir()
    create_execution_profile(
        tmp_path, {"profile_id": "fast", "provider_id": "local-openai", "instances": ["gpt-4o-mini"]}
    )
    set_implementation_state(tmp_path, "providers", "local-openai", ImplementationState(enabled=True))
    started, hold = _block_dispatch(monkeypatch)
    factory = AgentTaskFactory(tmp_path)

    task = factory.submit_raw("fast", prompt_body="hi")
    assert started.wait(timeout=2)

    assert task.status()["execution-profile-id"] == "fast"
    hold.set()


# ---------------------------------------------------------------------------
# AgentTask -- delegating handle, not cached state
# ---------------------------------------------------------------------------

def test_agent_task_status_re_reads_on_every_call(tmp_path: Path, monkeypatch):
    """Two independent AgentTask handles for the same request_id always agree,
    because neither caches -- both read the same durable record. Dispatch is
    held mid-flight so the record is stable across both reads."""
    _setup_agent(tmp_path)
    started, hold = _block_dispatch(monkeypatch)
    factory = AgentTaskFactory(tmp_path)
    task = factory.submit("reviewer-agent", prompt_body="hi")
    assert started.wait(timeout=2)

    handle_a = AgentTask(tmp_path, task.request_id)
    handle_b = AgentTask(tmp_path, task.request_id)

    assert handle_a.status() == handle_b.status()
    hold.set()


def test_agent_task_result_matches_status(tmp_path: Path, monkeypatch):
    _setup_agent(tmp_path)
    started, hold = _block_dispatch(monkeypatch)
    factory = AgentTaskFactory(tmp_path)
    task = factory.submit("reviewer-agent", prompt_body="hi")
    assert started.wait(timeout=2)

    assert task.result() == task.status()
    hold.set()


def test_agent_task_cancel_queued_request(tmp_path: Path, monkeypatch):
    """Occupy the only concurrency slot with a held request, then submit and
    cancel a second one while it is still queued -- deterministic, matching
    test_agents_gateway_api.py's own cancellation test pattern."""
    (tmp_path / ".audiagentic").mkdir(exist_ok=True)
    create_execution_profile(
        tmp_path,
        {
            "profile_id": "fast",
            "provider_id": "local-openai",
            "instances": ["gpt-4o-mini"],
            "params": {"max-concurrency": 1},
        },
    )
    set_implementation_state(tmp_path, "providers", "local-openai", ImplementationState(enabled=True))
    create_role(tmp_path, {"role_id": "reviewer", "instructions": "Review."})
    create_agent_definition(
        tmp_path,
        {
            "agent_id": "reviewer-agent",
            "name": "Reviewer Agent",
            "execution_profile_id": "fast",
            "role_id": "reviewer",
        },
    )
    started, hold = _block_dispatch(monkeypatch)
    factory = AgentTaskFactory(tmp_path)

    occupier = factory.submit("reviewer-agent", prompt_body="first")
    assert started.wait(timeout=2)
    queued_task = factory.submit("reviewer-agent", prompt_body="second")

    result = queued_task.cancel()
    assert result["state"] == "cancelled"
    hold.set()


def test_factory_get_rehydrates_existing_task(tmp_path: Path, monkeypatch):
    """A handle constructed via `factory.get(request_id)` behaves identically
    to the one returned by `submit` -- neither holds independent state."""
    _setup_agent(tmp_path)
    started, hold = _block_dispatch(monkeypatch)
    factory = AgentTaskFactory(tmp_path)
    original = factory.submit("reviewer-agent", prompt_body="hi")
    assert started.wait(timeout=2)

    rehydrated = factory.get(original.request_id)

    assert rehydrated.status() == original.status()
    hold.set()


def test_many_agent_task_handles_can_coexist(tmp_path: Path, monkeypatch):
    """No registry, no tracking -- construct as many handles as you like."""
    _setup_agent(tmp_path)
    started, hold = _block_dispatch(monkeypatch)
    factory = AgentTaskFactory(tmp_path)
    task = factory.submit("reviewer-agent", prompt_body="hi")
    assert started.wait(timeout=2)

    handles = [AgentTask(tmp_path, task.request_id) for _ in range(10)]
    statuses = [h.status() for h in handles]

    assert all(s == statuses[0] for s in statuses)
    hold.set()
