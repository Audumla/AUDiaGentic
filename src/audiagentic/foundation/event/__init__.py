"""Foundation event system.

Generic event infrastructure used by components to exchange events.
Swappable for external MQ (MQTT, Redis) via EventBusProtocol.

Components:
- EventBus / EventBusProtocol: in-process dispatch with SYNC/ASYNC modes
- EventEnvelope: canonical event wrapper
- FileEventStore: optional file-based persistence
- StructuredLog: OpenTelemetry-style append-only JSONL log
- EventLayerConfig: event-layer settings loaded from `.audiagentic/event/config.yaml`
- CodeFormatter: opt-in code formatting on task completion events
"""

from .envelope import EventEnvelope
from .event_bus import (
    DeliveryMode,
    EventBus,
    EventBusProtocol,
    SubscriptionHandle,
    get_bus,
    reset_bus,
)
from .event_config import (
    EventCycleDetectionSettings,
    EventLayerConfig,
    EventReplaySettings,
    EventStoreSettings,
    load_event_config,
)
from .event_exceptions import CycleDetectedError, EventBusError, PersistenceError, SubscriberError
from .event_log import StructuredLog, now_iso
from .event_store import FileEventStore
from .lifecycle_observer import (
    COMPONENT_CONFIG_CHANGED,
    COMPONENT_DISABLED,
    COMPONENT_ENABLED,
    COMPONENT_INSTALLED,
    COMPONENT_UNINSTALLED,
    subscribe_component_lifecycle,
)

__all__ = [
    "COMPONENT_CONFIG_CHANGED",
    "COMPONENT_DISABLED",
    "COMPONENT_ENABLED",
    "COMPONENT_INSTALLED",
    "COMPONENT_UNINSTALLED",
    "subscribe_component_lifecycle",
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
    "EventStoreSettings",
    "EventCycleDetectionSettings",
    "EventReplaySettings",
    "EventLayerConfig",
    "load_event_config",
    "StructuredLog",
    "now_iso",
    "get_bus",
    "reset_bus",
]
