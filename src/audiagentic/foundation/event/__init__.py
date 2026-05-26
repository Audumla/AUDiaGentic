"""Foundation event system.

Generic event infrastructure used by planning, knowledge, and other modules.
Swappable for external MQ (MQTT, Redis) via EventBusProtocol.

Components:
- EventBus / EventBusProtocol: in-process dispatch with SYNC/ASYNC modes
- EventEnvelope: canonical event wrapper
- FileEventStore: optional file-based persistence
- ReplayService: replay persisted events
- StructuredLog: OpenTelemetry-style append-only JSONL log
- EventService: publishes to local log + shared EventBus
- CodeFormatter: opt-in code formatting on task completion events
"""

from .bus import DeliveryMode, EventBus, EventBusProtocol, SubscriptionHandle, get_bus, reset_bus
from .envelope import EventEnvelope
from .exceptions import CycleDetectedError, EventBusError, PersistenceError, SubscriberError
from .log import StructuredLog, now_iso
from .replay import ReplayService
from .service import EventService
from .store import FileEventStore

__all__ = [
    "EventBus",
    "EventBusProtocol",
    "EventBusError",
    "DeliveryMode",
    "SubscriptionHandle",
    "CycleDetectedError",
    "SubscriberError",
    "PersistenceError",
    "EventEnvelope",
    "FileEventStore",
    "ReplayService",
    "StructuredLog",
    "EventService",
    "now_iso",
    "get_bus",
    "reset_bus",
]
