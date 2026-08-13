from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from audiagentic.components.agents.agents_paths import (
    agent_context_lock_path,
    agent_context_path,
    agent_context_root,
)
from audiagentic.components.agents.configuration.resolution import AgentConfigIdentity
from audiagentic.components.agents.context.contracts import AgentContextRecord, AgentContextState
from audiagentic.foundation.io import atomic_write_json, load_json_file
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.workflow import load_workflow, transition_allowed

_WORKFLOW = load_workflow(Path(__file__).parent.parent / "workflows.yaml", "agent-context")


class AgentContextStore:
    def create(self, project_root: Path, composition: AgentConfigIdentity, title: str | None = None, *, context_id: str | None = None) -> AgentContextRecord:
        context_id = context_id or f"ctx_{uuid4().hex}"
        now = _now()
        record = AgentContextRecord(context_id, composition, AgentContextState.OPEN, title, 0, now, now)
        path = agent_context_path(project_root, context_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with StartupLock(agent_context_lock_path(project_root, context_id)):
            if path.exists():
                raise FileExistsError(context_id)
            atomic_write_json(path, record.to_mapping())
        return record

    def get(self, project_root: Path, context_id: str) -> AgentContextRecord:
        return _from_mapping(load_json_file(agent_context_path(project_root, context_id)))

    def list(self, project_root: Path) -> tuple[AgentContextRecord, ...]:
        root = agent_context_root(project_root)
        if not root.exists():
            return ()
        return tuple(self.get(project_root, path.parent.name) for path in sorted(root.glob("*/record.json")))

    def transition(self, project_root: Path, context_id: str, target: AgentContextState, *, expected_revision: int) -> AgentContextRecord:
        path = agent_context_path(project_root, context_id)
        with StartupLock(agent_context_lock_path(project_root, context_id)):
            current = _from_mapping(load_json_file(path))
            if current.revision != expected_revision:
                raise RuntimeError("context revision conflict")
            if not transition_allowed(_WORKFLOW, current.state.value, target.value):
                raise ValueError("illegal context transition")
            updated = AgentContextRecord(current.context_id, current.composition, target, current.title, current.revision + 1, current.created_at, _now())
            atomic_write_json(path, updated.to_mapping())
            return updated


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _from_mapping(value: dict) -> AgentContextRecord:
    composition = AgentConfigIdentity(**value["composition"])
    return AgentContextRecord(value["context_id"], composition, AgentContextState(value["state"]), value.get("title"), int(value["revision"]), value["created_at"], value["updated_at"])
