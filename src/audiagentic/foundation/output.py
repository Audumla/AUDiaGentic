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
    if isinstance(message, ComponentOutputEvent):
        return message
    return ComponentOutputEvent(message=str(message))
