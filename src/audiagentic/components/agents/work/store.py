from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from audiagentic.components.agents.agents_paths import (
    agent_context_lock_path,
    agent_work_lock_path,
    agent_work_path,
    agent_work_root,
)
from audiagentic.components.agents.work.contracts import (
    AgentWorkRecord,
    AgentWorkState,
    AgentWorkWaitReason,
    WorkCommandReceipt,
)
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_json, load_json_file
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.workflow import load_workflow, transition_allowed

command_error = make_error_factory("CON", "AGW", "agent-work")
_TERMINAL = {AgentWorkState.COMPLETED, AgentWorkState.FAILED, AgentWorkState.CANCELLED, AgentWorkState.REJECTED}

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

    def accept_command(
        self, project_root: Path, context_id: str, *, work_id: str, command: dict, parent_work_id: str | None = None,
        exclusive: bool = False,
    ) -> WorkCommandReceipt:
        """Commit one caller command (and the Work, when new) in a single atomic record replacement.

        ``command`` carries ``delivery_key`` and ``digest`` plus the durable payload. The same key and digest
        is a replay and returns the first acceptance; the same key with another digest is a conflict; a new
        key on terminal Work is refused. Nothing else is written here: inputs, gateway admission and the
        execution link are projections rebuilt from this record.
        """
        if exclusive:
            # Lock order is always Context lock -> Work lock, and the Context lock is never taken while a Work lock
            # is held. It is held only for exclusive acceptance, so concurrent Work (A2A) is unaffected.
            agent_context_lock_path(project_root, context_id).parent.mkdir(parents=True, exist_ok=True)
            with StartupLock(agent_context_lock_path(project_root, context_id)):
                return self._accept_locked(project_root, context_id, work_id, command, parent_work_id, True)
        return self._accept_locked(project_root, context_id, work_id, command, parent_work_id, False)

    def _accept_locked(self, project_root, context_id, work_id, command, parent_work_id, exclusive):
        path = agent_work_path(project_root, work_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with StartupLock(agent_work_lock_path(project_root, work_id)):
            if exclusive:
                # A replay of an already accepted command is not a second prompt, so only a NEW command is refused.
                known = path.exists() and any(
                    c.get("delivery_key") == command["delivery_key"]
                    for c in _from_mapping(load_json_file(path)).commands)
                busy = [w.work_id for w in self.list(project_root)
                        if w.context_id == context_id and w.work_id != work_id and w.state not in _TERMINAL]
                if busy and not known:
                    raise command_error(167, "The Context already has outstanding Work; this acceptance is exclusive",
                                        context_id=context_id, work_id=busy[0])
            if path.exists():
                current = _from_mapping(load_json_file(path))
                if current.context_id != context_id:
                    raise command_error(160, "The Work belongs to a different Context", work_id=work_id)
                prior = next((c for c in current.commands if c.get("delivery_key") == command["delivery_key"]), None)
                if prior is not None:
                    if prior.get("digest") != command["digest"]:
                        raise command_error(161, "The delivery identity was already accepted with a different payload",
                                            work_id=work_id)
                    return WorkCommandReceipt(current, prior, True)
                if current.state in _TERMINAL:
                    raise command_error(162, "The Work is terminal and cannot accept a new command", work_id=work_id,
                                        state=current.state.value)
                updated = _with_commands(current, (*current.commands, command))
            else:
                now = _now()
                updated = AgentWorkRecord(work_id, context_id, AgentWorkState.SUBMITTED, None, None, parent_work_id,
                                          None, 0, now, now, (command,))
            atomic_write_json(path, updated.to_mapping())
            return WorkCommandReceipt(updated, command, False)

    def link_command_execution(
        self, project_root: Path, work_id: str, delivery_key: str, execution_id: str,
    ) -> AgentWorkRecord:
        """Record the gateway request that carries one accepted command (idempotent per command).

        A command keeps the first execution it was linked to; a second, different one is refused. The Work's
        ``active_execution_id`` follows the newest command, so the history of every execution stays in the
        commands while the existing single-slot readers keep working.
        """
        path = agent_work_path(project_root, work_id)
        with StartupLock(agent_work_lock_path(project_root, work_id)):
            current = _from_mapping(load_json_file(path))
            commands = list(current.commands)
            index = next((i for i, c in enumerate(commands) if c.get("delivery_key") == delivery_key), None)
            if index is None:
                raise command_error(165, "The command is not part of this Work", work_id=work_id)
            linked = commands[index].get("execution_id")
            if linked == execution_id:
                return current
            if linked:
                raise command_error(166, "The command is already linked to a different execution", work_id=work_id)
            commands[index] = {**commands[index], "execution_id": execution_id}
            newest = max(i for i, c in enumerate(commands) if c.get("execution_id"))
            updated = AgentWorkRecord(
                current.work_id, current.context_id, current.state, current.wait_reason,
                commands[newest]["execution_id"], current.parent_work_id, current.current_interaction_id,
                current.revision + 1, current.created_at, _now(), tuple(commands),
            )
            atomic_write_json(path, updated.to_mapping())
            return updated

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
            updated = AgentWorkRecord(current.work_id, current.context_id, target, current.wait_reason, active_execution_id or current.active_execution_id, current.parent_work_id, current.current_interaction_id, current.revision + 1, current.created_at, _now(), current.commands)
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
                current.revision + 1, current.created_at, _now(), current.commands,
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
                current.revision + 1, current.created_at, _now(), current.commands,
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
                current.revision + 1, current.created_at, _now(), current.commands,
            )
            atomic_write_json(path, updated.to_mapping())
            return updated


def _with_commands(current: AgentWorkRecord, commands: tuple) -> AgentWorkRecord:
    return AgentWorkRecord(current.work_id, current.context_id, current.state, current.wait_reason,
                           current.active_execution_id, current.parent_work_id, current.current_interaction_id,
                           current.revision + 1, current.created_at, _now(), commands)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _from_mapping(value: dict) -> AgentWorkRecord:
    reason = value.get("wait_reason")
    return AgentWorkRecord(value["work_id"], value["context_id"], AgentWorkState(value["state"]), AgentWorkWaitReason(reason) if reason else None, value.get("active_execution_id"), value.get("parent_work_id"), value.get("current_interaction_id"), int(value["revision"]), value["created_at"], value["updated_at"], tuple(value.get("commands") or ()))
