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
    """Return independent global/project/session concurrency limits.

    ``virtual-capacity`` remains the backwards-compatible global default. The
    three explicit dimensions are optional and may be set to ``unlimited``.
    A missing project/session limit is unbounded; a missing global limit keeps
    the historic ``virtual-capacity`` behaviour.
    """
    global_keys = ("global-capacity", "global_capacity", "global-concurrency", "global_concurrency")
    project_keys = ("project-capacity", "project_capacity", "project-concurrency", "project_concurrency")
    session_keys = ("session-capacity", "session_capacity", "session-concurrency", "session_concurrency")
    global_value = first_present(params, *global_keys)
    global_explicit = global_value is not None
    global_limit = resolve_virtual_capacity(params) if not global_explicit else _optional_capacity(params, *global_keys)
    return {
        "global": global_limit,
        "global-explicit": global_explicit,
        "project": _optional_capacity(params, *project_keys),
        "session": _optional_capacity(params, *session_keys),
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
