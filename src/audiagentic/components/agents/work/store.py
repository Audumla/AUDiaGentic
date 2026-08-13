from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from audiagentic.components.agents.agents_paths import (
    agent_work_lock_path,
    agent_work_path,
    agent_work_root,
)
from audiagentic.components.agents.work.contracts import (
    AgentWorkRecord,
    AgentWorkState,
    AgentWorkWaitReason,
)
from audiagentic.foundation.io import atomic_write_json, load_json_file
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.workflow import load_workflow, transition_allowed

_WORKFLOW = load_workflow(Path(__file__).parent.parent / "workflows.yaml", "agent-work")


class AgentWorkStore:
    def create(self, project_root: Path, context_id: str, *, work_id: str | None = None, parent_work_id: str | None = None) -> AgentWorkRecord:
        work_id = work_id or f"work_{uuid4().hex}"
        now = _now()
        record = AgentWorkRecord(work_id, context_id, AgentWorkState.SUBMITTED, None, None, parent_work_id, None, 0, now, now)
        path = agent_work_path(project_root, work_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with StartupLock(agent_work_lock_path(project_root, work_id)):
            if path.exists():
                raise FileExistsError(work_id)
            atomic_write_json(path, record.to_mapping())
        return record

    def get(self, project_root: Path, work_id: str) -> AgentWorkRecord:
        return _from_mapping(load_json_file(agent_work_path(project_root, work_id)))

    def list(self, project_root: Path) -> tuple[AgentWorkRecord, ...]:
        root = agent_work_root(project_root)
        if not root.exists():
            return ()
        return tuple(self.get(project_root, path.parent.name) for path in sorted(root.glob("*/record.json")))

    def transition(self, project_root: Path, work_id: str, target: AgentWorkState, *, expected_revision: int, active_execution_id: str | None = None) -> AgentWorkRecord:
        path = agent_work_path(project_root, work_id)
        with StartupLock(agent_work_lock_path(project_root, work_id)):
            current = _from_mapping(load_json_file(path))
            if current.revision != expected_revision:
                raise RuntimeError("work revision conflict")
            if not transition_allowed(_WORKFLOW, current.state.value, target.value):
                raise ValueError("illegal work transition")
            updated = AgentWorkRecord(current.work_id, current.context_id, target, current.wait_reason, active_execution_id or current.active_execution_id, current.parent_work_id, current.current_interaction_id, current.revision + 1, current.created_at, _now())
            atomic_write_json(path, updated.to_mapping())
            return updated

    def link_execution(self, project_root: Path, work_id: str, execution_id: str, *, expected_revision: int) -> AgentWorkRecord:
        """Attach the gateway request after admission without owning execution."""
        path = agent_work_path(project_root, work_id)
        with StartupLock(agent_work_lock_path(project_root, work_id)):
            current = _from_mapping(load_json_file(path))
            if current.revision != expected_revision:
                raise RuntimeError("work revision conflict")
            if current.active_execution_id and current.active_execution_id != execution_id:
                raise ValueError("work already links a different execution")
            updated = AgentWorkRecord(
                current.work_id, current.context_id, current.state, current.wait_reason,
                execution_id, current.parent_work_id, current.current_interaction_id,
                current.revision + 1, current.created_at, _now(),
            )
            atomic_write_json(path, updated.to_mapping())
            return updated

    def set_waiting(self, project_root: Path, work_id: str, *, interaction_id: str, reason: AgentWorkWaitReason, expected_revision: int) -> AgentWorkRecord:
        path = agent_work_path(project_root, work_id)
        with StartupLock(agent_work_lock_path(project_root, work_id)):
            current = _from_mapping(load_json_file(path))
            if current.revision != expected_revision:
                raise RuntimeError("work revision conflict")
            if current.state is not AgentWorkState.ACTIVE:
                raise ValueError("only active work can wait")
            updated = AgentWorkRecord(
                current.work_id, current.context_id, AgentWorkState.WAITING, reason,
                current.active_execution_id, current.parent_work_id, interaction_id,
                current.revision + 1, current.created_at, _now(),
            )
            atomic_write_json(path, updated.to_mapping())
            return updated

    def resume_waiting(self, project_root: Path, work_id: str, *, expected_revision: int) -> AgentWorkRecord:
        path = agent_work_path(project_root, work_id)
        with StartupLock(agent_work_lock_path(project_root, work_id)):
            current = _from_mapping(load_json_file(path))
            if current.revision != expected_revision:
                raise RuntimeError("work revision conflict")
            if current.state is not AgentWorkState.WAITING:
                raise ValueError("only waiting work can resume")
            updated = AgentWorkRecord(
                current.work_id, current.context_id, AgentWorkState.ACTIVE, None,
                current.active_execution_id, current.parent_work_id, None,
                current.revision + 1, current.created_at, _now(),
            )
            atomic_write_json(path, updated.to_mapping())
            return updated


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _from_mapping(value: dict) -> AgentWorkRecord:
    reason = value.get("wait_reason")
    return AgentWorkRecord(value["work_id"], value["context_id"], AgentWorkState(value["state"]), AgentWorkWaitReason(reason) if reason else None, value.get("active_execution_id"), value.get("parent_work_id"), value.get("current_interaction_id"), int(value["revision"]), value["created_at"], value["updated_at"])
