from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import get_bus

from .registry import all_descriptors

LifecycleHook = Callable[[str, dict[str, Any], dict[str, Any]], None]
StatusHook = Callable[[Path], "ComponentStatusPayload | None"]

_INITIALIZED = False
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComponentStatusPayload:
    enabled: bool
    configured: bool
    active_implementation: str | None = None
    missing_required: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise _status_error("enabled must be bool", field="enabled")
        if not isinstance(self.configured, bool):
            raise _status_error("configured must be bool", field="configured")
        if self.active_implementation is not None and not isinstance(
            self.active_implementation, str
        ):
            raise _status_error(
                "active_implementation must be str or None", field="active_implementation"
            )
        if not isinstance(self.missing_required, list):
            raise _status_error("missing_required must be a list", field="missing_required")
        for item in self.missing_required:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("option"), str)
                or not isinstance(item.get("description"), str)
            ):
                raise _status_error(
                    "missing_required entries must include string option and description",
                    field="missing_required",
                )
        if not isinstance(self.details, dict):
            raise _status_error("details must be dict", field="details")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "active_implementation": self.active_implementation,
            "missing_required": list(self.missing_required),
            "details": dict(self.details),
        }


def _status_error(message: str, **details: Any) -> AudiaGenticError:
    return AudiaGenticError(
        code="VAL-COMP-001",
        kind="components",
        message=message,
        details=details or None,
    )


@cache
def _resolve_hook(hook_path: str) -> LifecycleHook | None:
    module_name, _, fn_name = hook_path.rpartition(".")
    if not (module_name and fn_name):
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
        logger.error("%s '%s' raised: %s", failure_label, hook_path, exc, exc_info=True)
        return {"error": str(exc), "hook": hook_path}


_STATUS_HOOK_TIMEOUT_MS = 2000  # per-hook timeout in milliseconds


def get_component_status(descriptor: Any, project_root: Path) -> dict[str, Any] | None:
    """Invoke a component's status_hook and return the serialized status payload.

    Per-hook timing is logged at WARNING level when a hook exceeds
    _STATUS_HOOK_TIMEOUT_MS (2 seconds). Status hooks must be local,
    bounded, read-only — no subprocesses, network probes, locks, or large
    filesystem scans.
    """
    hook_path = getattr(descriptor, "status_hook", None)
    if not hook_path:
        return None
    fn = _resolve_hook(hook_path)
    if fn is None:
        logger.warning(
            "status_hook[%s]: could not resolve '%s'", descriptor.component_id, hook_path
        )
        return None
    start_ms = time.monotonic()
    try:
        result = fn(project_root)
    except AudiaGenticError:
        logger.error(
            "status_hook[%s] raised AudiaGenticError", descriptor.component_id, exc_info=True
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "status_hook[%s] '%s' raised: %s",
            descriptor.component_id,
            hook_path,
            exc,
            exc_info=True,
        )
        raise AudiaGenticError(
            code="INT-COMP-002",
            kind="components",
            message="component status hook failed",
            details={"component_id": descriptor.component_id, "hook": hook_path},
        ) from exc
    finally:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        if elapsed_ms > _STATUS_HOOK_TIMEOUT_MS:
            logger.warning(
                "status_hook[%s] took %.0fms (threshold: %dms) — consider making hook local, bounded, read-only",
                descriptor.component_id,
                elapsed_ms,
                _STATUS_HOOK_TIMEOUT_MS,
            )
    if result is None:
        return None
    if isinstance(result, ComponentStatusPayload):
        return result.to_dict()
    logger.error(
        "status_hook[%s] returned invalid payload type: %s",
        descriptor.component_id,
        type(result).__name__,
    )
    raise _status_error(
        "status hook must return ComponentStatusPayload or None",
        component_id=descriptor.component_id,
        hook=hook_path,
        returned_type=type(result).__name__,
    )


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
