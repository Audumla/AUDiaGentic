# foundation/event/

Generic event infrastructure for AUDiaGentic. Provides in-process pub/sub dispatch, optional file persistence, and a swappable transport protocol for external MQ (MQTT, Redis, Kafka).

## Purpose

The event layer is the communication backbone between components. It allows components to exchange events without direct coupling. The layer is **transport-agnostic** — the in-process `EventBus` can be replaced with an external MQ implementation without changing component code.

**Key design principle:** The event bus is passive infrastructure. Components register their own subscribers; the bus does not know about event semantics.

## Architecture

```
Publisher → StructuredLog (JSONL) + EventBus → Subscribers
                                              ↓
                                        FileEventStore (optional)
```

## Components

### EventBus / EventBusProtocol (`event_bus.py`)

Core in-process pub/sub with SYNC/ASYNC delivery modes.

- **EventBusProtocol** — abstract interface for swappable transports. Implement this to replace the in-process bus with MQTT, Redis, Kafka, etc.
- **EventBus** — reference in-process implementation with:
  - Wildcard pattern matching (`*` = one segment, `**` = zero or more)
  - SYNC dispatch (immediate, blocking) and ASYNC dispatch (background thread pool)
  - Subscriber isolation — one handler failure does not affect others
  - Cycle detection via `propagation_depth` (max 10) and `correlation_id` chain tracking
  - Thread-safe subscription management
- **SubscriptionHandle** — returned by `subscribe()`, used for `unsubscribe()`
- **get_bus() / reset_bus()** — singleton accessors. Use `get_bus()` for convenience; prefer explicit DI in production code.

**Pattern matching:**
- `planning.item.state.changed` — exact match
- `planning.item.*` — matches `planning.item.created`, `planning.item.deleted`
- `planning.**` — matches all planning events

### EventEnvelope (`envelope.py`)

Canonical dataclass wrapper for all events. Auto-generates metadata:

- `id` — UUID4 (auto)
- `type` — dot-notation event type (e.g., `planning.item.state.changed`)
- `version` — envelope schema version (default: 1)
- `occurred_at` — UTC ISO 8601 timestamp (auto)
- `source_component` — emitting component name
- `correlation_id` — optional, for tracing event chains
- `subject` — optional dict with `{kind, id}` of the affected item
- `payload` — user-provided data dict
- `metadata` — user-provided metadata dict
- `is_replay` — set to `True` during replay
- `propagation_depth` — incremented during state propagation chains

Serializable via `to_dict()` / `from_dict()`.

### StructuredLog (`event_log.py`)

Append-only JSONL structured logger aligned with the OpenTelemetry Logs data model. Each record includes `timestamp`, `observed_timestamp`, `severity_text`, `body`, and `attributes`, with optional `trace_id` and `span_id`. Event publishers use `emit_event()` to project `EventEnvelope` into this schema. Domain modules should delegate operational/audit records here instead of deriving component-specific log formats inside reusable foundation code.

### FileEventStore (`event_store.py`)

Optional file-based event persistence with atomic writes (temp file + rename). Best-effort — failures are logged, never block publishing.

- `persist(envelope)` — atomic write to `runtime/foundation/events/`
- `query(from_timestamp, to_timestamp, event_type_pattern)` — filtered retrieval
- `cleanup(older_than_days)` — retention management
- Filename format: `{timestamp}_{sanitized_type}_{event_id}.json`

### Configuration (`event_config.py`)

Dataclass-based configuration loaded from `.audiagentic/event/config.yaml`.

- `EventStoreSettings` — enabled, path, retention_days
- `EventCycleDetectionSettings` — max_depth, correlation_tracking
- `EventReplaySettings` — dispatch_on_replay
- `EventLayerConfig` — top-level event-layer settings object
- `load_event_config(root)` — loads from file or returns defaults

### Exceptions (`event_exceptions.py`)

- **EventBusError** — base exception
- **CycleDetectedError** — propagation depth exceeded or correlation_id cycle
- **SubscriberError** — handler failure (caught and logged by bus)
- **PersistenceError** — file write failure (caught and logged, never blocks publish)

## Event Type Convention

Follows spec-23 dot-notation: `{component}.{noun}.{verb}` or `{component}.{noun}.{subnoun}.{verb}`.

**Canonical planning events:**
- `planning.item.created` — item created
- `planning.item.updated` — item content or metadata updated
- `planning.item.deleted` — item soft or hard deleted
- `planning.item.state.changed` — state transition
- `planning.item.moved` — domain changed
- `planning.item.claimed` — ownership claimed
- `planning.item.unclaimed` — ownership released
- `planning.item.archived` — item archived
- `planning.item.restored` — item restored from archive
- `planning.item.superseded` — item superseded
- `planning.maintain.completed` — maintenance cycle completed
- `planning.reconcile.completed` — reconciliation completed

## Usage Patterns

### Publishing an event

```python
from audiagentic.foundation.event import get_bus, DeliveryMode

bus = get_bus()
bus.publish(
    "planning.item.state.changed",
    {"id": "task-001", "old_state": "draft", "new_state": "in_progress"},
    metadata={"subject": {"kind": "task", "id": "task-001"}},
    mode=DeliveryMode.SYNC,
)
```

### Subscribing to events

```python
from audiagentic.foundation.event import get_bus

bus = get_bus()

def my_handler(event_type, payload, metadata):
    print(f"{event_type}: {payload}")

handle = bus.subscribe("planning.item.state.changed", my_handler)
# Later: bus.unsubscribe(handle)
```

### Swapping to external MQ

```python
from audiagentic.foundation.event import EventBusProtocol, DeliveryMode, SubscriptionHandle

class MQTTBus(EventBusProtocol):
    def publish(self, event_type, payload, metadata=None, mode=DeliveryMode.SYNC): ...
    def subscribe(self, pattern, handler): ...
    def unsubscribe(self, handle): ...
```

## Standard References

- **standard-10** (Component architecture standard) — requirements 25-30 cover event-driven architecture, passive utilities, swappable bus, handler isolation, and opt-in subscriptions
- **standard-12** (Event subscription configuration standard) — defines adapter/handler YAML config format, event type patterns, payload filters, and file locations
- **spec-23** (Interoperability event layer specification) — event protocol, envelope format, namespace convention

## File Map

| File | Responsibility |
|------|----------------|
| `event_bus.py` | EventBus, EventBusProtocol, singleton, pattern matching, cycle detection |
| `envelope.py` | EventEnvelope dataclass with auto-metadata |
| `event_log.py` | StructuredLog — OpenTelemetry-style JSONL writer |
| `event_store.py` | FileEventStore — optional file persistence with atomic writes |
| `event_config.py` | EventLayerConfig dataclasses and YAML loader |
| `event_exceptions.py` | EventBusError, CycleDetectedError, SubscriberError, PersistenceError |
