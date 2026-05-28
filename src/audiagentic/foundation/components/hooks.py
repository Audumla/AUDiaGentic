from __future__ import annotations

import logging
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from audiagentic.foundation.event import get_bus

from .registry import all_descriptors

LifecycleHook = Callable[[str, dict[str, Any], dict[str, Any]], None]

_INITIALIZED = False
logger = logging.getLogger(__name__)


@cache
def _resolve_hook(hook_path: str) -> LifecycleHook | None:
    module_name, _, fn_name = hook_path.rpartition(".")
    if not module_name or not fn_name:
        return None
    try:
        module = __import__(module_name, fromlist=[fn_name])
        hook = getattr(module, fn_name, None)
    except Exception:  # noqa: BLE001
        return None
    return hook if callable(hook) else None


def invoke_hook(
    hook_path: str,
    *args: Any,
    failure_label: str = "hook",
    **kwargs: Any,
) -> Any:
    """Resolve and invoke a dotted-path hook with structured failure logging.

    Returns the hook's return value, None if the hook could not be resolved,
    or {"error": ..., "hook": hook_path} if the hook raises.
    """
    fn = _resolve_hook(hook_path)
    if fn is None:
        logger.warning("%s: could not resolve '%s'", failure_label, hook_path)
        return None
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        _log.error("%s '%s' raised: %s", failure_label, hook_path, exc, exc_info=True)
        return {"error": str(exc), "hook": hook_path}


def get_component_status(descriptor: Any, project_root: Path) -> dict[str, Any] | None:
    """Invoke a component's status_hook and return its payload, or None if absent."""
    hook_path = getattr(descriptor, "status_hook", None)
    if not hook_path:
        return None
    result = invoke_hook(
        hook_path,
        project_root,
        failure_label=f"status_hook[{descriptor.component_id}]",
    )
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    return {"status-hook-error": "hook did not return a dict"}


def _dispatch_component_lifecycle(event_type: str, payload: dict, metadata: dict) -> None:
    for descriptor in all_descriptors().values():
        if not descriptor.lifecycle_hook:
            continue
        invoke_hook(
            descriptor.lifecycle_hook,
            event_type,
            payload,
            metadata,
            failure_label=f"lifecycle_hook[{descriptor.component_id}]",
        )


def initialize_lifecycle_hook_dispatch() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    get_bus().subscribe("lifecycle.component.*", _dispatch_component_lifecycle)
    _INITIALIZED = True

