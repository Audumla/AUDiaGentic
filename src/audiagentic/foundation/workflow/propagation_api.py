"""Interface contract for state propagation engine.

Defines the minimal interface the propagation engine expects from its host context.
"""

from __future__ import annotations

from typing import Any, Protocol


class WorkflowItemAPI(Protocol):
    """Minimal interface the propagation engine needs from its host.

    The engine only uses these methods:
    - lookup(): Get an item by ID
    - state(): Update an item's state
    - _scan(): Scan all items (reverse parent lookup)
    """

    def lookup(self, item_id: str) -> Any: ...

    def state(self, id_: str, new_state: str, metadata: dict[str, Any]) -> Any: ...

    def _scan(self) -> list[Any]: ...
