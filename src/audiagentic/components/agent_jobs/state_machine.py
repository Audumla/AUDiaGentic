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

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    states_in_set,
    transition_allowed,
)
from audiagentic.runtime.state import jobs_store as store

logger = logging.getLogger(__name__)

_JOB_WORKFLOW = load_workflow(Path(__file__).with_name("workflows.yaml"), "job")

# Public, config-derived views of the job lifecycle.
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    state: set(targets) for state, targets in (_JOB_WORKFLOW.get("transitions") or {}).items()
}
TERMINAL_STATES: set[str] = set(states_in_set(_JOB_WORKFLOW, "terminal"))


def ensure_transition(current_state: str, new_state: str) -> None:
    if not is_known_state(_JOB_WORKFLOW, current_state):
        raise AudiaGenticError(
            code="VAL-STATE-001",
            kind="agent-jobs",
            message="unknown job state",
            details={"state": current_state},
        )
    if not transition_allowed(_JOB_WORKFLOW, current_state, new_state):
        raise AudiaGenticError(
            code="CON-STATE-001",
            kind="agent-jobs",
            message="illegal job state transition",
            details={"from": current_state, "to": new_state},
        )


def transition_job(
    job_record: dict[str, Any],
    new_state: str,
    *,
    now_fn: Callable[[], str] | None = None,
) -> dict[str, Any]:
    ensure_transition(job_record["state"], new_state)
    updated = dict(job_record)
    updated["state"] = new_state
    updated["updated-at"] = (now_fn or now_iso_z)()
    return updated


def transition_and_persist(
    project_root: Path,
    job_id: str,
    new_state: str,
    *,
    now_fn: Callable[[], str] | None = None,
) -> dict[str, Any]:
    record = store.read_job_record(project_root, job_id)
    updated = transition_job(record, new_state, now_fn=now_fn)
    store.write_job_record(project_root, updated)
    return updated
