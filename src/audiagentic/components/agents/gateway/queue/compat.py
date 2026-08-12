"""Explicit migration adapters for pre-AS101 profile queue parameters.

New scheduling code must use source capacity declarations. These validators
remain only for legacy callers that still submit profile parameters; they are
not part of the resolved execution-profile contract.
"""

from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.mapping import first_present
from audiagentic.foundation.contracts.errors import AudiaGenticError


def resolve_max_concurrency(params: dict[str, Any]) -> int:
    value = first_present(params, "max-concurrency", "max_concurrency")
    if value is None:
        return 1
    if not isinstance(value, int) or isinstance(value, bool):
        raise AudiaGenticError("VAL-AGW-020", "agents", "legacy max-concurrency must be an integer", {"value": value})
    if value < 1:
        raise AudiaGenticError("VAL-AGW-021", "agents", "legacy max-concurrency must be >= 1", {"value": value})
    return value


def resolve_queue_max_size(params: dict[str, Any], max_concurrency: int) -> int:
    value = first_present(params, "queue-max-size", "queue_max_size")
    if value is None:
        return max(8, max_concurrency * 2)
    if not isinstance(value, int) or isinstance(value, bool):
        raise AudiaGenticError("VAL-AGW-022", "agents", "legacy queue-max-size must be an integer", {"value": value})
    if value < 1:
        raise AudiaGenticError("VAL-AGW-023", "agents", "legacy queue-max-size must be >= 1", {"value": value})
    return value


__all__ = ["resolve_max_concurrency", "resolve_queue_max_size"]
