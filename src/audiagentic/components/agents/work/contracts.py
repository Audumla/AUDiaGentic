from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentWorkState(str, Enum):
    SUBMITTED = "submitted"
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class AgentWorkWaitReason(str, Enum):
    USER_INPUT = "user-input"
    APPROVAL = "approval"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    DEPENDENCY = "dependency"
    CHILD_WORK = "child-work"


@dataclass(frozen=True, slots=True)
class AgentWorkRecord:
    work_id: str
    context_id: str
    state: AgentWorkState
    wait_reason: AgentWorkWaitReason | None
    active_execution_id: str | None
    parent_work_id: str | None
    current_interaction_id: str | None
    revision: int
    created_at: str
    updated_at: str

    def to_mapping(self) -> dict[str, Any]:
        return {"work_id": self.work_id, "context_id": self.context_id, "state": self.state.value, "wait_reason": self.wait_reason.value if self.wait_reason else None, "active_execution_id": self.active_execution_id, "parent_work_id": self.parent_work_id, "current_interaction_id": self.current_interaction_id, "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at}


@dataclass(frozen=True, slots=True)
class WorkInputMessage:
    message_id: str
    text: str
    inputs: Mapping[str, Any]
    created_at: str
