"""Interface contract for state propagation engine dependencies.

This module defines the minimal interface that the propagation engine expects
from the planning API. This allows for easier testing and potential future
implementations.
"""

from __future__ import annotations

from typing import Any, Protocol


class PlanningAPIInterface(Protocol):
    """Minimal interface contract for planning API used by propagation engine.

    The propagation engine only uses these methods from PlanningAPI:
    - lookup(): Get an item by ID
    - state(): Update an item's state
    - _scan(): Scan all items (used for reverse parent lookup)
    """

    def lookup(self, item_id: str) -> Any:
        """Look up an item by ID.

        Args:
            item_id: Item ID to look up

        Returns:
            ItemView object with .data dict and .kind attribute, or None if not found
        """
        ...

    def state(self, id_: str, new_state: str, metadata: dict[str, Any]) -> Any:
        """Update an item's state.

        Args:
            id_: Item ID to update
            new_state: New state to set
            metadata: Event metadata

        Returns:
            Updated item or result of state change
        """
        ...

    def _scan(self) -> list[Any]:
        """Scan all planning items.

        Returns:
            List of ItemView objects
        """
        ...
