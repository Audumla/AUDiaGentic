"""Component-lifecycle event vocabulary and observer subscription helper.

Event names are bus vocabulary and live here beside the bus. The lifecycle
package publishes them (foundation/lifecycle/observers.py); component
observers subscribe through :func:`subscribe_component_lifecycle`, which owns
payload validation, component filtering, and event dispatch so observers keep
only their handler bodies.

Payload schema:
  component_id : str   — the component that changed state
  project_root : Path  — project root Path (in-process, not serialized)
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from .event_bus import get_bus

COMPONENT_INSTALLED = "lifecycle.component.installed"
COMPONENT_UNINSTALLED = "lifecycle.component.uninstalled"
COMPONENT_ENABLED = "lifecycle.component.enabled"
COMPONENT_DISABLED = "lifecycle.component.disabled"
COMPONENT_CONFIG_CHANGED = "lifecycle.component.config_changed"


class LifecycleEventPayload(TypedDict):
    """Payload published with every lifecycle.component.* event.

    A TypedDict is a plain dict at runtime — this is static typing only.
    project_root is a live Path (in-process bus, not serialized; the event
    store persists its string form).
    """

    component_id: str
    project_root: Path


# handler(project_root, payload, metadata)
LifecycleHandler = Callable[[Path, LifecycleEventPayload, dict[str, Any]], None]
_DISPATCHERS: list[Callable[[str, dict, dict], None]] = []


def subscribe_component_lifecycle(
    component_id: str | None,
    *,
    on_installed: LifecycleHandler | None = None,
    on_enabled: LifecycleHandler | None = None,
    on_disabled: LifecycleHandler | None = None,
    on_uninstalled: LifecycleHandler | None = None,
    on_config_changed: LifecycleHandler | None = None,
) -> Callable[[str, dict, dict], None]:
    """Subscribe callbacks to component lifecycle events on the shared bus.

    Subscribes once to ``lifecycle.component.*``; the returned dispatcher
    validates payload types (``project_root``: Path, ``component_id``: str),
    filters to ``component_id`` (``None`` observes every component), and
    invokes the matching callback with ``(project_root, payload, metadata)``.
    The bus subscribes by topic pattern only — topics do not encode component
    IDs — so this helper is where component filtering lives.

    Returns the dispatcher (useful for tests and unsubscription).
    """
    handlers: dict[str, LifecycleHandler | None] = {
        COMPONENT_INSTALLED: on_installed,
        COMPONENT_ENABLED: on_enabled,
        COMPONENT_DISABLED: on_disabled,
        COMPONENT_UNINSTALLED: on_uninstalled,
        COMPONENT_CONFIG_CHANGED: on_config_changed,
    }

    def _dispatch(event_type: str, payload: dict, metadata: dict) -> None:
        handler = handlers.get(event_type)
        if handler is None:
            return
        # Runtime guard stays despite the TypedDict: events arrive from the
        # bus as untyped dicts and external publishers are not type-checked.
        project_root = payload.get("project_root")
        subject_id = payload.get("component_id")
        if not isinstance(project_root, Path) or not isinstance(subject_id, str):
            return
        if component_id is not None and subject_id != component_id:
            return
        handler(project_root, payload, metadata)  # type: ignore[arg-type]

    _DISPATCHERS.append(_dispatch)
    get_bus().subscribe("lifecycle.component.*", _dispatch)
    return _dispatch


def _resubscribe_all() -> None:
    for dispatcher in _DISPATCHERS:
        get_bus().subscribe("lifecycle.component.*", dispatcher)
