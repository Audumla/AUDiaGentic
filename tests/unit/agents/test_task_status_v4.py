"""Offline contract tests for the slim V4 task-status projection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from audiagentic.components.agents.status.task_status_v4 import (
    TaskStatusContractError,
    project_task_status_v4,
)
from audiagentic.foundation.transports.agent_status import (
    AgentLifecycle,
    AgentOutcome,
    AgentStatusScope,
    AgentStatusSnapshot,
)
from audiagentic.foundation.contracts.schema_registry import validate_with_schema


def _record(state: str, **extra: object) -> dict[str, object]:
    record: dict[str, object] = {
        "request-id": "req-1",
        "state": state,
    }
    record.update(extra)
    return record


def _snapshot(
    record: dict[str, object],
    lifecycle: AgentLifecycle,
    outcome: AgentOutcome | None = None,
) -> AgentStatusSnapshot:
    return AgentStatusSnapshot(
        scope=AgentStatusScope.EXECUTION_REQUEST,
        lifecycle=lifecycle,
        outcome=outcome,
        request_id=str(record["request-id"]),
        projected_at="2026-08-24T00:00:00Z",
    )


def test_queued_is_pending_waiting_with_null_outcome() -> None:
    result = project_task_status_v4(_record("queued"))

    assert result == {
        "request-id": "req-1",
        "lifecycle": "pending",
        "activity": "waiting",
        "outcome": None,
    }


def test_running_is_active_running_without_provider_details() -> None:
    result = project_task_status_v4(
        _record("running"), _snapshot(_record("running"), AgentLifecycle.UNKNOWN)
    )

    assert result == {
        "request-id": "req-1",
        "lifecycle": "active",
        "activity": "running",
        "outcome": None,
    }


def test_running_cancel_request_is_active_cancelling() -> None:
    record = _record("running", **{"cancel-requested": True})
    result = project_task_status_v4(record, _snapshot(record, AgentLifecycle.ACTIVE))

    assert result["lifecycle"] == "active"
    assert result["activity"] == "cancelling"
    assert result["outcome"] is None


@pytest.mark.parametrize(
    ("agent_lifecycle", "expected_activity"),
    [("waiting", "waiting"), ("completing", "completing")],
)
def test_running_uses_canonical_agent_status_activity(
    agent_lifecycle: str, expected_activity: str
) -> None:
    record = _record("running")
    result = project_task_status_v4(
        record, _snapshot(record, AgentLifecycle(agent_lifecycle))
    )

    assert result["lifecycle"] == "active"
    assert result["activity"] == expected_activity
    assert result["outcome"] is None


@pytest.mark.parametrize(
    ("state", "outcome"),
    [
        ("completed", "success"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
        ("interrupted", "interrupted"),
        ("rejected", "rejected"),
        ("timed-out", "timed-out"),
        ("expired", "expired"),
        ("abandoned", "abandoned"),
        ("superseded", "superseded"),
    ],
)
def test_terminal_states_have_one_outcome_and_no_activity(
    state: str, outcome: str
) -> None:
    record = _record(state)
    result = project_task_status_v4(
        record,
        _snapshot(record, AgentLifecycle.TERMINAL, AgentOutcome(outcome)),
    )

    assert result == {
        "request-id": "req-1",
        "lifecycle": "terminal",
        "activity": None,
        "outcome": outcome,
    }


def test_v4_has_exactly_four_keys_and_no_internal_fields() -> None:
    record = _record(
        "running",
        **{
            "diagnostics": {"failure-code": "secret"},
            "worker-id": "worker-secret",
            "provider-metadata": {"chat-url": "https://example.invalid"},
            "response-artifact": {"artifact-id": "final-response"},
        },
    )
    result = project_task_status_v4(record, _snapshot(record, AgentLifecycle.ACTIVE))

    assert set(result) == {"request-id", "lifecycle", "activity", "outcome"}


@pytest.mark.parametrize(
    "record",
    [
        {"state": "running"},
        {"request-id": "req-1", "state": "unknown"},
        {
            "request-id": "req-1",
            "state": "completed",
        },
    ],
)
def test_contradictory_or_incomplete_state_fails_closed(record: dict[str, object]) -> None:
    snapshot = None
    if record.get("state") == "completed":
        snapshot = SimpleNamespace(
            scope=AgentStatusScope.EXECUTION_REQUEST,
            request_id="req-1",
            lifecycle=AgentLifecycle.ACTIVE,
            outcome=None,
        )
    with pytest.raises(TaskStatusContractError):
        project_task_status_v4(record, snapshot)


def test_snapshot_scope_and_identity_must_match_request() -> None:
    record = _record("running")
    wrong_scope = SimpleNamespace(
        scope=AgentStatusScope.SESSION,
        request_id="req-1",
        lifecycle=AgentLifecycle.ACTIVE,
        outcome=None,
    )
    wrong_id = SimpleNamespace(
        scope=AgentStatusScope.EXECUTION_REQUEST,
        request_id="req-other",
        lifecycle=AgentLifecycle.ACTIVE,
        outcome=None,
    )

    with pytest.raises(TaskStatusContractError):
        project_task_status_v4(record, wrong_scope)
    with pytest.raises(TaskStatusContractError):
        project_task_status_v4(record, wrong_id)


def test_dispatching_is_active_running_even_when_v3_snapshot_is_unknown() -> None:
    record = _record("dispatching")
    snapshot = _snapshot(record, AgentLifecycle.UNKNOWN)

    assert project_task_status_v4(record, snapshot) == {
        "request-id": "req-1",
        "lifecycle": "active",
        "activity": "running",
        "outcome": None,
    }


def test_v4_projection_validates_against_canonical_schema() -> None:
    payload = project_task_status_v4(_record("queued"))
    assert validate_with_schema("task-status-v4", payload) == []
    assert validate_with_schema("task-status-v4", {**payload, "diagnostics": {}})
