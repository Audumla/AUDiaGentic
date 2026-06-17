"""Minimal interface contract the propagation engine expects from its host."""

from __future__ import annotations

from typing import Any, Protocol


class WorkflowItemAPI(Protocol):
    def lookup(self, item_id: str) -> Any: ...

    def state(self, id_: str, new_state: str, metadata: dict[str, Any]) -> Any: ...

    def _scan(self) -> list[Any]: ...
