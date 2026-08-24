"""Provider-neutral capacity policy for undeclared instances (AS101)."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.mapping import first_present
from audiagentic.foundation.contracts.errors import AudiaGenticError

_UNLIMITED = {"unlimited", "none", "null", "infinite", "infinity"}


def _optional_capacity(params: dict[str, Any], *keys: str) -> int | None:
    """Resolve an optional capacity; ``None``/``unlimited`` means unbounded."""
    value = first_present(params, *keys)
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in _UNLIMITED:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AudiaGenticError(
            "VAL-AGW-020", "agents",
            "capacity must be a positive integer or 'unlimited'",
            {"value": value, "keys": list(keys)},
        )
    return value


def resolve_virtual_capacity(params: dict[str, Any]) -> int | None:
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
    if isinstance(value, str) and value.strip().lower() in _UNLIMITED:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AudiaGenticError("VAL-AGW-020", "agents", "virtual capacity must be a positive integer", {"value": value})
    return value


def resolve_capacity_limits(params: dict[str, Any]) -> dict[str, int | None | bool]:
    """Return global/project active-task concurrency limits.

    ``virtual-capacity`` remains the backwards-compatible global default. The
    the two execution dimensions are optional and may be set to ``unlimited``.
    A missing project limit is unbounded; a missing global limit keeps
    the historic ``virtual-capacity`` behaviour.
    """
    global_keys = ("global-capacity", "global_capacity", "global-concurrency", "global_concurrency")
    project_keys = ("project-capacity", "project_capacity", "project-concurrency", "project_concurrency")
    # Key presence, rather than value truthiness, distinguishes an explicit
    # YAML null (which is an intentional unlimited setting) from omission.
    global_explicit = any(key in params for key in global_keys)
    global_limit = resolve_virtual_capacity(params) if not global_explicit else _optional_capacity(params, *global_keys)
    return {
        "global": global_limit,
        "global-explicit": global_explicit,
        "project": _optional_capacity(params, *project_keys),
        # Retained as a null compatibility field so older callers can inspect
        # the mapping without accidentally applying a legacy per-session
        # capacity. Persistent sessions are capacity-neutral; the queue still
        # enforces one active turn per session through its turn lock.
        "session": None,
    }

def resolve_pending_capacity(params: dict[str, Any], virtual_capacity: int | None) -> int:
    value = first_present(
        params,
        "pending-capacity",
        "pending_capacity",
        "queue-max-size",
        "queue_max_size",
    )
    if value is None:
        return max(8, (virtual_capacity or 1) * 2)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AudiaGenticError("VAL-AGW-022", "agents", "pending capacity must be a positive integer", {"value": value})
    return value

__all__ = ["resolve_capacity_limits", "resolve_pending_capacity", "resolve_virtual_capacity"]

