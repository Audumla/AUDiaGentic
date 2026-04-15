"""AUDiaGentic interoperability event layer.

Lightweight event bus for cross-component communication with minimal client API.
Supports SYNC/ASYNC dispatch, wildcard pattern matching, and optional persistence.

MQ Migration: EventBusProtocol defines abstract interface for future transport
adapters (Redis, MQTT, etc.). Components depend on protocol, not concrete impl.
"""

from __future__ import annotations

from .bus import DeliveryMode, EventBus, EventBusProtocol, SubscriptionHandle
from .envelope import EventEnvelope
from .exceptions import CycleDetectedError, EventBusError, SubscriberError
from .formatters import CodeFormatter

__all__ = [
    "EventBus",
    "EventBusProtocol",
    "EventEnvelope",
    "DeliveryMode",
    "SubscriptionHandle",
    "EventBusError",
    "CycleDetectedError",
    "SubscriberError",
    "CodeFormatter",
]

# Singleton instance (bootstrap convenience only)
# Prefer explicit dependency injection for test isolation and component architecture compliance
_bus_instance: EventBus | None = None


def get_bus() -> EventBus:
    """Get the singleton EventBus instance.

    Returns:
        EventBus: The singleton instance

    Warning:
        This singleton pattern is provided for bootstrap convenience only.
        For production code and tests, prefer explicit dependency injection:

        ```python
        # Preferred: Explicit instantiation
        from audiagentic.interoperability import EventBus
        bus = EventBus(source_component="my_component")

        # Or via dependency injection container
        class Application:
            def __init__(self):
                self.bus = EventBus(source_component="app")
        ```

    Note:
        Direct singleton access violates standard-0011 (Component Architecture).
        Use only when refactoring legacy code or in bootstrap scenarios.
    """
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = EventBus()
    return _bus_instance


def reset_bus() -> None:
    """Reset the singleton EventBus instance.

    Use this in tests to isolate test cases.

    Warning:
        This function modifies global state. Prefer creating new EventBus instances
        for test isolation instead of relying on global state reset.
    """
    global _bus_instance
    _bus_instance = None
