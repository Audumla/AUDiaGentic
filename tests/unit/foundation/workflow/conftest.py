"""Shared fake WorkflowConfig and WorkflowContext for foundation/workflow unit tests.

No PlanningAPI, no filesystem, no event bus. Tests in this package depend only on
``audiagentic.foundation.workflow`` — zero coupling to any host component.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from audiagentic.foundation.workflow import ItemView, StateMachine

# ── Fake config ───────────────────────────────────────────────────────────────

@dataclass
class FakeConfig:
    """Minimal in-memory WorkflowConfig.

    Default workflow:  draft -> active -> done | cancelled
    State sets:        initial={draft}, active={active}, complete={done},
                       terminal={done, cancelled}, blocked={}
    Priorities:        draft=0, active=10, done=20, cancelled=20
    """

    _workflows: dict[str, dict] = field(default_factory=lambda: {
        "*": {
            "values": ["draft", "active", "done", "cancelled"],
            "transitions": {
                "draft":     ["active"],
                "active":    ["done", "cancelled"],
                "done":      [],
                "cancelled": [],
            },
        }
    })
    _state_sets: dict[str, set] = field(default_factory=lambda: {
        "initial":  {"draft"},
        "active":   {"active"},
        "complete": {"done"},
        "terminal": {"done", "cancelled"},
        "closed":   {"done", "cancelled"},
        "blocked":  set(),
    })
    _priorities: dict[str, int] = field(default_factory=lambda: {
        "draft": 0, "active": 10, "done": 20, "cancelled": 20,
    })
    _actions: dict[str, dict] = field(default_factory=dict)
    _lifecycle_transitions: dict[tuple, tuple] = field(default_factory=dict)

    def initial_state(self, kind: str, workflow: str | None = None) -> str:
        return "draft"

    def workflow_for(self, kind: str, workflow_name: str | None = None) -> dict:
        return self._workflows.get(kind) or self._workflows["*"]

    def workflow_states(self, kind: str) -> list[str]:
        return list(self.workflow_for(kind)["values"])

    def state_in_set(self, kind: str, state: str | None, set_name: str,
                     workflow: str | None = None) -> bool:
        return state in self._state_sets.get(set_name, set())

    def states_in_set(self, kind: str, set_name: str,
                      workflow: str | None = None) -> list[str]:
        return sorted(self._state_sets.get(set_name, set()))

    def state_priority(self, kind: str, state: str, workflow: str | None = None) -> int:
        return self._priorities.get(state, 0)

    def lifecycle_action(self, name: str) -> dict:
        return self._actions.get(name, {})

    def lifecycle_action_for_transition(self, kind: str, old: str, new: str,
                                        workflow: str | None = None) -> tuple:
        return self._lifecycle_transitions.get((kind, old, new), (None, None))

    def workflow_action(self, name: str) -> dict:
        return {}

    def reference_fields(self, kind: str) -> list[str]:
        return []

    def reference_field_shape(self, f: str) -> str:
        return "scalar_ref"

    def reference_field_targets(self, f: str) -> list[str]:
        return []

    def seeded_reference_fields(self, kind: str) -> dict[str, str]:
        return {}

    def default_guidance(self) -> str:
        return ""

    def build_creation_extra_fields(self, kind: str, **kw: Any) -> dict:
        return {}

    def is_soft_deleted(self, data: dict) -> bool:
        return bool(data.get("deleted"))


# ── Fake context ──────────────────────────────────────────────────────────────

class FakeContext:
    """In-memory WorkflowContext — no filesystem, no event bus, no planning code."""

    def __init__(
        self,
        items: dict[str, ItemView] | None = None,
        config: FakeConfig | None = None,
    ) -> None:
        self.items: dict[str, ItemView] = dict(items or {})
        self.config = config or FakeConfig()
        self.root = Path("/fake/root")
        self.events: list[dict] = []
        self.saved: list[tuple[str, dict]] = []
        self.indexed: int = 0
        self._machine: StateMachine | None = None

    # -- convenience ---------------------------------------------------------

    def add_item(
        self, id_: str, kind: str, state: str = "draft", **extra: Any
    ) -> ItemView:
        data = {"id": id_, "state": state, **extra}
        item = ItemView(
            kind=kind,
            path=Path(f"/fake/{kind}/{id_}.md"),
            data=data,
            body="",
        )
        self.items[id_] = item
        return item

    def last_event(self, event_type: str | None = None) -> dict | None:
        matches = [e for e in self.events if event_type is None or e["type"] == event_type]
        return matches[-1] if matches else None

    # -- WorkflowContext protocol ---------------------------------------------

    @property
    def _fsm(self) -> StateMachine:
        if self._machine is None:
            self._machine = StateMachine(self)
        return self._machine

    def lookup(self, id_: str) -> ItemView | None:
        return self.items.get(id_)

    def _find(self, id_: str) -> ItemView:
        try:
            return self.items[id_]
        except KeyError:
            raise KeyError(f"Item not found: {id_}")

    def _scan(self) -> list[ItemView]:
        return list(self.items.values())

    def save(self, item: ItemView) -> None:
        self.saved.append((item.data["id"], dict(item.data)))

    def _publish_event(
        self, event_type: str, payload: dict, metadata: dict | None = None, *, mode: Any = None
    ) -> None:
        self.events.append({"type": event_type, "payload": dict(payload), "metadata": metadata})

    def state(
        self, id_: str, new_state: str, *,
        reason: str | None = None, actor: str | None = None,
        metadata: dict | None = None,
    ) -> ItemView:
        return self._fsm.state(id_, new_state, reason=reason, actor=actor, metadata=metadata)

    def new(self, kind: str, label: str, summary: str, **kw: Any) -> ItemView:
        raise NotImplementedError("FakeContext.new not implemented in this test")

    def relink(self, src: str, f: str, dst: str, *, seq: int | None = None,
               display: str | None = None) -> None:
        pass

    def index(self) -> None:
        self.indexed += 1


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def cfg() -> FakeConfig:
    return FakeConfig()


@pytest.fixture()
def ctx() -> FakeContext:
    return FakeContext()
