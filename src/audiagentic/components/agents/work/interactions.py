"""Work waiting uses the Foundation interaction owner."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.interaction.api import get_response, request_interaction

from .contracts import AgentWorkRecord, AgentWorkWaitReason
from .service import get_work
from .store import AgentWorkStore


def wait_for_interaction(
    project_root: Path,
    work_id: str,
    *,
    kind: str,
    title: str,
    reason: AgentWorkWaitReason,
    description: str = "",
    choices: tuple[str, ...] = (),
    ttl_seconds: int = 1800,
) -> AgentWorkRecord:
    work = get_work(project_root, work_id)
    interaction_id = request_interaction(
        kind,
        title,
        description=description,
        choices=choices,
        source_kind="agent-work",
        source_id=work_id,
        ttl_seconds=ttl_seconds,
        project_root=project_root,
    )
    return AgentWorkStore().set_waiting(
        project_root,
        work_id,
        interaction_id=interaction_id,
        reason=reason,
        expected_revision=work.revision,
    )


def resume_after_interaction(project_root: Path, work_id: str) -> AgentWorkRecord | None:
    work = get_work(project_root, work_id)
    if not work.current_interaction_id:
        return work
    response = get_response(work.current_interaction_id, project_root=project_root)
    if response is None:
        return None
    return AgentWorkStore().resume_waiting(project_root, work_id, expected_revision=work.revision)
