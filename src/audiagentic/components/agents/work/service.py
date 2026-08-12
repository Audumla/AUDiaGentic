from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.context.service import get_context
from audiagentic.components.agents.work.contracts import (
    AgentWorkRecord,
    AgentWorkState,
    WorkInputMessage,
)
from audiagentic.components.agents.work.inputs import append_work_input
from audiagentic.components.agents.work.store import AgentWorkStore


def submit_work(project_root: Path, context_id: str, message: WorkInputMessage, *, work_id: str | None = None) -> AgentWorkRecord:
    context = get_context(project_root, context_id)
    if context.state.value != "open":
        raise ValueError("context is closed")
    store = AgentWorkStore()
    work = store.create(project_root, context_id, work_id=work_id)
    append_work_input(project_root, work.work_id, message)
    return store.transition(project_root, work.work_id, AgentWorkState.ACTIVE, expected_revision=work.revision)


def get_work(project_root: Path, work_id: str) -> AgentWorkRecord:
    return AgentWorkStore().get(project_root, work_id)


def list_work(project_root: Path) -> tuple[AgentWorkRecord, ...]:
    return AgentWorkStore().list(project_root)


def add_work_message(project_root: Path, work_id: str, message: WorkInputMessage) -> AgentWorkRecord:
    """Append one caller message without creating a second Work record."""
    work = get_work(project_root, work_id)
    if work.state in {AgentWorkState.COMPLETED, AgentWorkState.FAILED, AgentWorkState.CANCELLED, AgentWorkState.REJECTED}:
        raise ValueError("cannot add a message to terminal work")
    append_work_input(project_root, work_id, message)
    return work


def cancel_work(project_root: Path, work_id: str) -> AgentWorkRecord:
    work = get_work(project_root, work_id)
    if work.state in {AgentWorkState.COMPLETED, AgentWorkState.FAILED, AgentWorkState.CANCELLED, AgentWorkState.REJECTED}:
        return work
    return AgentWorkStore().transition(project_root, work_id, AgentWorkState.CANCELLED, expected_revision=work.revision)


def read_work_output(project_root: Path, work_id: str) -> dict:
    """Project output from the gateway output owner; Work stores no output."""
    work = get_work(project_root, work_id)
    if not work.active_execution_id:
        return {"work_id": work_id, "execution_id": None, "events": []}
    from audiagentic.components.agents.gateway.output import read_request_output

    return read_request_output(project_root, work.active_execution_id)
