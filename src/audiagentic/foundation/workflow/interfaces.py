"""Interfaces for generic workflow engine.

WorkflowConfig: config methods the workflow engine needs from its host component.
WorkflowContext: runtime operations (lookup, state transitions, scans, events).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class WorkflowConfig(Protocol):
    """Config interface for workflow engine.

    Implementing component provides these methods to drive workflow behaviour.
    """

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
    """Runtime context the workflow engine uses for item operations.

    The host component (e.g., PlanningAPI) provides this context to the
    generic workflow engine. The engine only touches these methods, not
    the host's internals.
    """

    @property
    def root(self) -> Path: ...

    @property
    def config(self) -> WorkflowConfig: ...

    def lookup(self, item_id: str) -> Any: ...

    def _scan(self) -> list[Any]: ...

    def _find(self, item_id: str) -> Any: ...

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
    ) -> Any: ...

    def relink(
        self, src: str, field: str, dst: str, *, seq: int | None = None, display: str | None = None
    ) -> None: ...

    def index(self) -> None: ...
