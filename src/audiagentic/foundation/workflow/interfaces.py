"""Interfaces for the generic workflow engine.

WorkflowConfig: config methods the engine needs from its host component.
WorkflowContext: runtime operations (lookup, scan, save, publish, etc.).

Both are Protocols — any object with matching attributes satisfies them.
The workflow package itself has no dependency on the host implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .item import ItemView


class WorkflowConfig(Protocol):
    def initial_state(self, kind: str, workflow: str | None = ...) -> str: ...

    def workflow_for(self, kind: str, workflow_name: str | None) -> dict[str, Any]: ...

    def workflow_states(self, kind: str) -> list[str]: ...

    def state_in_set(
        self, kind: str, state: str | None, set_name: str, workflow: str | None
    ) -> bool: ...

    def states_in_set(self, kind: str, set_name: str, workflow: str | None) -> list[str]: ...

    def state_priority(self, kind: str, state: str, workflow: str | None) -> int: ...

    def lifecycle_action(self, name: str) -> dict[str, Any]: ...

    def lifecycle_action_for_transition(
        self, kind: str, old: str, new: str, workflow: str | None
    ) -> tuple[str, dict[str, Any] | None]: ...

    def workflow_action(self, name: str) -> dict[str, Any]: ...

    def state_change_event_type(self) -> str: ...

    def reference_fields(self, kind: str) -> list[str]: ...

    def reference_field_shape(self, field: str) -> str: ...

    def reference_field_targets(self, field: str) -> list[str]: ...

    def seeded_reference_fields(self, kind: str) -> dict[str, str]: ...

    def default_guidance(self) -> str: ...

    def build_creation_extra_fields(
        self,
        kind: str,
        *,
        summary: str,
        guidance: str,
        profile: str | None,
        current_understanding: str | None,
        open_questions: list[str] | None,
        source: str | None,
        context: str | None,
    ) -> dict[str, Any]: ...

    def is_soft_deleted(self, data: dict[str, Any]) -> bool: ...


class WorkflowContext(Protocol):
    """Minimal runtime context the engine uses for item operations.

    Hosts implement these; the engine does not touch host internals.
    """

    @property
    def root(self) -> Path: ...

    @property
    def config(self) -> WorkflowConfig: ...

    def lookup(self, item_id: str) -> ItemView | None: ...

    def _find(self, item_id: str) -> ItemView: ...

    def _scan(self) -> list[ItemView]: ...

    def save(self, item: ItemView) -> None: ...

    def _publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None,
        *,
        mode: Any | None = None,
    ) -> None: ...

    def new(
        self,
        kind: str,
        label: str,
        summary: str,
        *,
        domain: str | None = None,
        workflow: str | None = None,
        refs: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
        check_duplicates: bool = True,
        **kwargs: Any,
    ) -> ItemView: ...

    def relink(
        self, src: str, field: str, dst: str, *, seq: int | None = None, display: str | None = None
    ) -> None: ...

    def state(
        self,
        id_: str,
        new_state: str,
        *,
        reason: str | None = None,
        actor: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ItemView: ...

    def index(self) -> None: ...
