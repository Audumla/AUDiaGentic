"""Shared component output events for CLIs, MCP servers, and UIs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

OutputLevel = Literal["debug", "info", "warning", "error"]
OutputKind = Literal["progress", "log"]


@dataclass(frozen=True)
class ComponentOutputEvent:
    """Structured status/log message emitted by component APIs."""

    message: str
    kind: OutputKind = "progress"
    level: OutputLevel = "info"
    progress: float | None = None
    total: float | None = None
    logger: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


ComponentOutputSink = Callable[[ComponentOutputEvent], None]


def coerce_output_event(message: str | ComponentOutputEvent) -> ComponentOutputEvent:
    """Return the event unchanged, or wrap a plain string as a progress event."""
    if isinstance(message, ComponentOutputEvent):
        return message
    return ComponentOutputEvent(message=str(message))


def emit_or_push_status(
    output: ComponentOutputSink | None,
    component: str,
    message: str,
    *,
    kind: OutputKind = "log",
    level: OutputLevel = "info",
    **data: Any,
) -> None:
    """Call `output` if given, else fall back to the operator-facing push_status.

    Shared glue for the common "on_progress: ComponentOutputSink | None"
    parameter pattern: programmatic callers who wire a sink get a structured
    ComponentOutputEvent; plain CLI callers who wire nothing still see the
    message via `foundation.interaction.push_status` instead of it silently
    vanishing.
    """
    if output is not None:
        output(ComponentOutputEvent(message=message, kind=kind, level=level, data=data))
        return
    from audiagentic.foundation.interaction import push_status

    push_status(component, message, level=level, details=data)
