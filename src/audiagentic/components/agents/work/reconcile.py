"""Work reconciliation seam; gateway remains the execution authority."""
from __future__ import annotations

from pathlib import Path

from .contracts import AgentWorkRecord, AgentWorkState
from .store import AgentWorkStore


def reconcile_work(project_root: Path, work: AgentWorkRecord, *, execution_state: str) -> AgentWorkRecord:
    """Project one gateway execution state onto the durable Work lifecycle.

    The gateway remains the execution authority; this function only performs
    the Work-side terminal/state projection and is safe to replay after a
    process restart.
    """
    if work.state in {
        AgentWorkState.COMPLETED,
        AgentWorkState.FAILED,
        AgentWorkState.CANCELLED,
        AgentWorkState.REJECTED,
    }:
        return work
    normalized = execution_state.strip().lower()
    target = {
        "queued": AgentWorkState.ACTIVE,
        "admitted": AgentWorkState.ACTIVE,
        "running": AgentWorkState.ACTIVE,
        "active": AgentWorkState.ACTIVE,
        "waiting": AgentWorkState.WAITING,
        "completed": AgentWorkState.COMPLETED,
        "succeeded": AgentWorkState.COMPLETED,
        "failed": AgentWorkState.FAILED,
        "interrupted": AgentWorkState.FAILED,
        "rejected": AgentWorkState.REJECTED,
        "cancelled": AgentWorkState.CANCELLED,
        "canceled": AgentWorkState.CANCELLED,
    }.get(normalized)
    if target is None or target == work.state:
        return work
    return AgentWorkStore().transition(
        project_root,
        work.work_id,
        target,
        expected_revision=work.revision,
    )


def reconcile_linked_execution(project_root: Path, work: AgentWorkRecord) -> AgentWorkRecord:
    """Read gateway status and project it onto Work after restart/recovery."""
    if not work.active_execution_id:
        # The Gateway idempotency index is the recovery authority for the
        # admitted-but-not-yet-linked crash window. Re-submit through the
        # public application seam with the deterministic Work message key;
        # Gateway admission returns the original request on replay.
        from audiagentic.components.agents.gateway.client import get_gateway_client
        from audiagentic.components.agents.work.inputs import latest_work_input

        message = latest_work_input(project_root, work.work_id)
        replayed = get_gateway_client(project_root).submit_agent_work(
            project_root,
            work.context_id,
            {
                "message_id": message.message_id,
                "text": message.text,
                "inputs": dict(message.inputs),
                "created_at": message.created_at,
            },
            work_id=work.work_id,
        )
        return AgentWorkStore().get(project_root, replayed["work_id"])
    from audiagentic.components.agents.gateway.client import get_gateway_client

    execution = get_gateway_client(project_root).get_execution_request(
        project_root,
        work.active_execution_id,
    )
    return reconcile_work(
        project_root,
        work,
        execution_state=str(execution.get("state", "")),
    )
