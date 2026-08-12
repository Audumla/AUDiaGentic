"""Provider-neutral capacity policy for undeclared instances (AS101)."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.mapping import first_present
from audiagentic.foundation.contracts.errors import AudiaGenticError


def resolve_virtual_capacity(params: dict[str, Any]) -> int:
    value = first_present(
        params,
        "virtual-capacity",
        "virtual_capacity",
        # Older execution-profile callers used the clearer public names;
        # keep them as compatibility aliases while virtual-capacity remains
        # the canonical gateway scheduler key.
        "max-concurrency",
        "max_concurrency",
    )
    if value is None:
        return 1
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AudiaGenticError("VAL-AGW-020", "agents", "virtual capacity must be a positive integer", {"value": value})
    return value

def resolve_pending_capacity(params: dict[str, Any], virtual_capacity: int) -> int:
    value = first_present(
        params,
        "pending-capacity",
        "pending_capacity",
        "queue-max-size",
        "queue_max_size",
    )
    if value is None:
        return max(8, virtual_capacity * 2)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AudiaGenticError("VAL-AGW-022", "agents", "pending capacity must be a positive integer", {"value": value})
    return value

__all__ = ["resolve_pending_capacity", "resolve_virtual_capacity"]
