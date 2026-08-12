from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from audiagentic.components.agents.configuration.resolution import AgentConfigIdentity


class AgentContextState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class AgentContextRecord:
    context_id: str
    composition: AgentConfigIdentity
    state: AgentContextState
    title: str | None
    revision: int
    created_at: str
    updated_at: str

    def to_mapping(self) -> dict[str, Any]:
        return {"context_id": self.context_id, "composition": self.composition.__dict__ if hasattr(self.composition, "__dict__") else {field: getattr(self.composition, field) for field in self.composition.__dataclass_fields__}, "state": self.state.value, "title": self.title, "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at}
