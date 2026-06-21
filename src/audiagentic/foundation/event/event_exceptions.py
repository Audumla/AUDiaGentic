"""Custom exceptions for the event layer."""

from __future__ import annotations

from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


class EventBusError(AudiaGenticError):
    """Base exception for EventBus errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INT-EVT-001",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            kind="event-bus",
            message=message,
            details=details or {},
        )


class CycleDetectedError(EventBusError):
    """Raised when a cycle is detected in event propagation.

    This occurs when:
    - propagation_depth >= max_depth (default: 10)
    - correlation_id is already in current chain
    """

    def __init__(
        self,
        message: str,
        event_id: str | None = None,
        propagation_depth: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        details = {
            "event-id": event_id,
            "propagation-depth": propagation_depth,
            "correlation-id": correlation_id,
        }
        super().__init__(message, code="CON-EVT-001", details=details)
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "propagation_depth", propagation_depth)
        object.__setattr__(self, "correlation_id", correlation_id)


class SubscriberError(EventBusError):
    """Raised when a subscriber handler fails.

    This exception is caught and logged by the EventBus,
    preventing one subscriber failure from affecting others.
    """

    def __init__(
        self,
        message: str,
        pattern: str | None = None,
        handler_name: str | None = None,
        event_type: str | None = None,
    ) -> None:
        details = {
            "pattern": pattern,
            "handler-name": handler_name,
            "event-type": event_type,
        }
        super().__init__(message, code="INT-EVT-002", details=details)
        object.__setattr__(self, "pattern", pattern)
        object.__setattr__(self, "handler_name", handler_name)
        object.__setattr__(self, "event_type", event_type)


class PersistenceError(EventBusError):
    """Raised when event persistence fails.

    This exception is caught and logged, not propagated to publisher.
    Persistence is best-effort and should not block publishing.
    """

    def __init__(
        self,
        message: str,
        event_id: str | None = None,
        path: str | None = None,
    ) -> None:
        details = {"event-id": event_id, "path": path}
        super().__init__(message, code="IO-EVT-001", details=details)
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "path", path)
