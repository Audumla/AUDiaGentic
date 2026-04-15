"""Custom exceptions for the interoperability event layer."""

from __future__ import annotations


class EventBusError(Exception):
    """Base exception for EventBus errors."""

    pass


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
        super().__init__(message)
        self.event_id = event_id
        self.propagation_depth = propagation_depth
        self.correlation_id = correlation_id


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
        super().__init__(message)
        self.pattern = pattern
        self.handler_name = handler_name
        self.event_type = event_type


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
        super().__init__(message)
        self.event_id = event_id
        self.path = path
