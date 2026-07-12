"""Job state machine.

The job lifecycle (states + legal transitions) is defined in ``workflows.yaml``
and validated through the shared ``foundation.workflow`` transition primitives.
This module owns only job-specific concerns: persistence and error reporting.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs import jobs_store as store
from audiagentic.components.agent_jobs.events import (
    record_job_timeline_event,
    state_to_event_name,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.workflow import (
    TransitionConfig,
    TransitionEngine,
    load_workflow,
    states_in_set,
)

logger = logging.getLogger(__name__)

_JOB_WORKFLOW = load_workflow(Path(__file__).with_name("workflows.yaml"), "job")

# Public, config-derived views of the job lifecycle.
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    state: set(targets) for state, targets in (_JOB_WORKFLOW.get("transitions") or {}).items()
}
TERMINAL_STATES: set[str] = set(states_in_set(_JOB_WORKFLOW, "terminal"))
_ENGINE = TransitionEngine(
    TransitionConfig(
        transitions={state: frozenset(targets) for state, targets in LEGAL_TRANSITIONS.items()},
        terminal_states=frozenset(TERMINAL_STATES),
    )
)


def ensure_transition(current_state: str, new_state: str) -> None:
    reason = _ENGINE.check(current_state, new_state)
    if reason == "unknown-current":
        raise AudiaGenticError(
            code="VAL-STATE-001",
            kind="agent-jobs",
            message="unknown job state",
            details={"state": current_state},
        )
    if reason is not None:
        raise AudiaGenticError(
            code="CON-STATE-001",
            kind="agent-jobs",
            message="illegal job state transition",
            details={"from": current_state, "to": new_state},
        )


def is_terminal_state(state: str | None) -> bool:
    return _ENGINE.is_terminal(state)


def transition_job(
    job_record: dict[str, Any],
    new_state: str,
    *,
    now_fn: Callable[[], str] | None = None,
    correlation_id: str | None = None,
    trigger_id: str | None = None,
) -> dict[str, Any]:
    ensure_transition(job_record["state"], new_state)
    updated = dict(job_record)
    updated["state"] = new_state
    updated["updated-at"] = (now_fn or now_iso_z)()
    if trigger_id is not None:
        updated["trigger-id"] = trigger_id
    return updated


def transition_and_persist(
    project_root: Path,
    job_id: str,
    new_state: str,
    *,
    now_fn: Callable[[], str] | None = None,
    correlation_id: str | None = None,
    trigger_id: str | None = None,
) -> dict[str, Any]:
    record = store.read_job_record(project_root, job_id)
    updated = transition_job(record, new_state, now_fn=now_fn, correlation_id=correlation_id, trigger_id=trigger_id)
    store.write_job_record(project_root, updated)
    event_name = state_to_event_name(new_state)
    if event_name is not None:
        attrs: dict[str, Any] = {"previous-state": record["state"]}
        if trigger_id is not None:
            attrs["trigger-id"] = trigger_id
        request_id = record.get("request-id") or record.get("packet-id")
        if request_id is not None:
            attrs["request-id"] = request_id
        record_job_timeline_event(
            project_root,
            job_id,
            event_name,
            state=new_state,
            attributes=attrs,
            correlation_id=correlation_id,
        )
    return updated
