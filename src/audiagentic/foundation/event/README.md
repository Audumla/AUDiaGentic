# foundation/event/

Generic event infrastructure for AUDiaGentic. Provides in-process pub/sub dispatch, optional file persistence, replay, and a swappable transport protocol for external MQ (MQTT, Redis, Kafka).

## Purpose

The event layer is the communication backbone between components. It allows planning, knowledge, and future components to exchange events without direct coupling. The layer is **transport-agnostic** — the in-process `EventBus` can be replaced with an external MQ implementation without changing component code.

**Key design principle:** The event bus is passive infrastructure. Components register their own subscribers; the bus does not know about event semantics.

## Architecture

```
Publisher → EventService → EventLog (JSONL) + EventBus → Subscribers
                                        ↓
                                  FileEventStore (optional)
                                        ↓
                                  ReplayService
```

## Components

### EventBus / EventBusProtocol (`bus.py`)

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

### EventService (`service.py`)

Thin publisher that writes to both `EventLog` (local JSONL) and `EventBus` (shared dispatch). Workflow-specific behavior (propagation, automation) lives in event subscribers, not here.

- `publish(event_type, payload, metadata, mode)` — emits to log + bus
- `sync_delivery_mode()` — returns SYNC mode for planning lifecycle
- `supports_sync` — always `True` for in-process bus

### EventLog (`log.py`)

Append-only JSONL file logger. Each line is a JSON record: `{"ts": "...", "event": "...", ...payload}`. No dependencies on planning or workflow code.

### FileEventStore (`store.py`)

Optional file-based event persistence with atomic writes (temp file + rename). Best-effort — failures are logged, never block publishing.

- `persist(envelope)` — atomic write to `runtime/foundation/events/`
- `query(from_timestamp, to_timestamp, event_type_pattern)` — filtered retrieval
- `cleanup(older_than_days)` — retention management
- Filename format: `{timestamp}_{sanitized_type}_{event_id}.json`

### AsyncQueue (`queue.py`)

Threading-based background worker for ASYNC mode events. Uses `queue.Queue` for thread safety.

- `get_instance()` — singleton
- `start()` / `stop(timeout)` — lifecycle
- `enqueue(event_type, payload, metadata)` — add event
- V1: Events lost on crash (`persist_on_checkpoint: false`)
- V2: Optional disk persistence on checkpoint

### ReplayService (`replay.py`)

Replays persisted events from `FileEventStore`. Optionally re-dispatches to subscribers.

- `replay(from_timestamp, to_timestamp, event_type_pattern)` — returns count of replayed events
- `dispatch_on_replay` — when `True`, replayed events trigger subscribers

### CodeFormatter (`formatters.py`)

Opt-in subscriber that runs `ruff format` + `ruff check --fix` on task source files when a task transitions to `done`. Registered via `bootstrap.setup_code_formatter()`.

### Configuration (`config.py`)

Dataclass-based configuration loaded from `.audiagentic/event/config.yaml`.

- `EventStoreConfig` — enabled, path, retention_days
- `AsyncQueueConfig` — enabled, max_queue_size, shutdown_timeout, persist_on_checkpoint
- `CycleDetectionConfig` — max_depth, correlation_tracking
- `ReplayConfig` — dispatch_on_replay
- `load_config(root)` — loads from file or returns defaults

### Bootstrap (`bootstrap.py`)

Opt-in registration functions. Nothing subscribes at import time.

- `setup_code_formatter(project_root)` — registers CodeFormatter as event subscriber

### Exceptions (`exceptions.py`)

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
from audiagentic.foundation.event import EventService, EventLog, get_bus
from pathlib import Path

# Via EventService (log + bus):
log = EventLog(Path("runtime/planning/events.jsonl"))
service = EventService(log)
service.publish(
    "planning.item.state.changed",
    {"id": "task-001", "old_state": "draft", "new_state": "in_progress"},
    {"subject": {"kind": "task", "id": "task-001"}},
    mode="sync",
)

# Direct to bus:
bus = get_bus()
bus.publish("planning.item.created", {"id": "task-002"}, mode=DeliveryMode.SYNC)
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
| `bus.py` | EventBus, EventBusProtocol, singleton, pattern matching, cycle detection |
| `envelope.py` | EventEnvelope dataclass with auto-metadata |
| `service.py` | EventService — publishes to log + bus |
| `log.py` | EventLog — append-only JSONL file writer |
| `store.py` | FileEventStore — optional file persistence with atomic writes |
| `queue.py` | AsyncQueue — threading-based background worker |
| `replay.py` | ReplayService — replay persisted events |
| `config.py` | EventConfig dataclasses and YAML loader |
| `bootstrap.py` | Opt-in subscription registration |
| `formatters.py` | CodeFormatter — ruff on task completion |
| `exceptions.py` | EventBusError, CycleDetectedError, SubscriberError, PersistenceError |
