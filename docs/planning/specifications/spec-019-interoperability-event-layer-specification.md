---
id: spec-019
label: Interoperability event layer specification
state: in_progress
summary: Lightweight in-process event bus with a transport-agnostic protocol that
  enables clean migration to MQTT or other message brokers without changing component
  call sites
request_refs:
- request-017
- request-018
standard_refs:
- standard-0005
- standard-0006
- standard-0011
---







# Purpose

Create a lightweight interoperability event layer that lets components publish and subscribe to post-commit facts without direct coupling. V1 is an in-process implementation. The architecture ensures that migrating to MQTT, Redis Pub/Sub, or any other message broker requires only a new adapter and a bootstrap change — no changes to components that publish or subscribe.

**Design principle:** Components depend on the protocol, not the implementation.

# Scope

**In scope (V1):**

- `EventBusProtocol` — the transport-agnostic contract all implementations must satisfy
- `InProcessEventBus` — V1 implementation: sync/async dispatch, pattern matching, subscriber isolation
- `FileEventStore` — optional append-only persistence for replay and audit
- `ReplayService` — re-publishes persisted events with `is_replay` flag
- `AsyncQueue` — background worker for ASYNC delivery mode
- `EventEnvelope` — canonical event wrapper with auto-generated metadata
- Cycle detection via `propagation_depth` and `correlation_id`
- Bootstrap wiring: `init_bus()` / `get_bus()` factory — no singleton, explicit injection
- Planning component integration: emit `planning.item.state.changed` after state commits
- Hook bridge: route compatible post-commit hooks through canonical events without removing legacy hooks
- Integration tests covering publish/subscribe, isolation, persistence, and replay

**Out of scope (V1) — deferred:**

- MQTT, Redis, or any external broker adapter (adapter slot reserved in `adapters/`, not implemented)
- Knowledge component integration (follow-on after core is stable)
- Hook system removal (separate task after migration is proven)
- Event schema registry and governance
- CLI diagnostics and event management commands
- Performance benchmarking tasks
- State propagation engine (request-018 / spec-020)

# Architecture

## Transport Protocol Abstraction

The central design decision: every component that publishes or subscribes uses `EventBusProtocol`, not a concrete class. Bootstrap wiring chooses the implementation. This is the seam that enables MQTT migration.

```
src/audiagentic/interoperability/
├── __init__.py       # init_bus(), get_bus() factory
├── protocol.py       # EventBusProtocol, SubscriptionHandle, DeliveryMode
├── envelope.py       # EventEnvelope dataclass
├── bus.py            # InProcessEventBus — implements EventBusProtocol
├── store.py          # FileEventStore — optional persistence
├── replay.py         # ReplayService
├── queue.py          # AsyncQueue — background ASYNC worker
├── config.py         # Config loading
├── exceptions.py     # InteropError, CycleDetectedError
└── adapters/
    └── __init__.py   # Adapter registration slot (empty in V1)

.audiagentic/interoperability/
└── config.yaml       # Runtime configuration
```

## Protocol Definition

```python
# protocol.py
from typing import Protocol, Callable, Any, runtime_checkable
from enum import Enum

class DeliveryMode(Enum):
    SYNC = "SYNC"    # blocking — all handlers complete before publish returns
    ASYNC = "ASYNC"  # non-blocking — queued to background worker

class SubscriptionHandle:
    """Opaque token returned by subscribe(). Pass to unsubscribe()."""

@runtime_checkable
class EventBusProtocol(Protocol):
    """
    Transport-agnostic event bus contract.

    V1 implementation: InProcessEventBus (bus.py)
    Future adapters:   MQTTEventBus, RedisEventBus (adapters/)

    Migrating to MQTT requires only:
      1. Implement MQTTEventBus satisfying this protocol
      2. Change: init_bus(InProcessEventBus(config))
             to: init_bus(MQTTEventBus(mqtt_config))
      3. No changes to any component that publishes or subscribes
    """
    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        mode: DeliveryMode = DeliveryMode.SYNC,
    ) -> None: ...

    def subscribe(
        self,
        pattern: str,
        handler: Callable[[str, dict, dict], None],
    ) -> SubscriptionHandle: ...

    def unsubscribe(self, handle: SubscriptionHandle) -> None: ...

    def close(self) -> None: ...
```

## Bootstrap Wiring

No singleton. The bus is injected at startup and accessed via `get_bus()`.

```python
# __init__.py
_bus: EventBusProtocol | None = None

def init_bus(bus: EventBusProtocol) -> None:
    """Call once at application startup with the chosen implementation."""
    global _bus
    _bus = bus

def get_bus() -> EventBusProtocol:
    """Return the active bus. Raises RuntimeError if init_bus() not called."""
    if _bus is None:
        raise RuntimeError("Event bus not initialised. Call init_bus() first.")
    return _bus
```

**V1 bootstrap:**
```python
from audiagentic.interoperability import init_bus
from audiagentic.interoperability.bus import InProcessEventBus

init_bus(InProcessEventBus(config))
```

**Future MQTT bootstrap — zero component changes:**
```python
from audiagentic.interoperability import init_bus
from audiagentic.interoperability.adapters.mqtt import MQTTEventBus

init_bus(MQTTEventBus(mqtt_config))
```

## Adapter Pattern

Future transport adapters live in `adapters/` and implement `EventBusProtocol`. They are independent packages or optional installs — not imported by core code. The adapter is responsible for mapping protocol calls to broker primitives. Pattern matching, envelope generation, and cycle detection may be handled by the broker (e.g., MQTT topic filters) or re-implemented in the adapter.

The `adapters/__init__.py` stub exists in V1 so the package structure is in place without requiring implementation.

# Requirements

## IL-1: Protocol contract
- `EventBusProtocol` defined using `typing.Protocol` with `@runtime_checkable`
- All four methods (`publish`, `subscribe`, `unsubscribe`, `close`) are required
- `InProcessEventBus` must satisfy `isinstance(bus, EventBusProtocol)` at runtime
- No component outside `interoperability/` may import `InProcessEventBus` directly; they import only from `protocol.py` or the package `__init__.py`

## IL-2: Event types and patterns
- Event types use dot-notation hierarchy: `planning.item.state.changed`
- `subscribe(pattern)` supports single-segment wildcard: `*` matches exactly one segment
  - `planning.item.*` matches `planning.item.state.changed`
  - `planning.item.*` does not match `planning.item.sub.changed`
- Multiple subscribers per pattern are supported
- Handler signature: `handler(event_type: str, payload: dict, metadata: dict) -> None`

## IL-3: Event envelope
Auto-generated by the bus — emitters do not construct these:

- `id` — uuid4
- `type` — event type string
- `occurred_at` — UTC ISO 8601 timestamp
- `source_component` — from config default or caller metadata
- `correlation_id` — optional; from caller metadata; used for cycle detection
- `propagation_depth` — integer, incremented per hop; default 0
- `is_replay` — boolean; `true` during replay only
- `payload` — caller-provided dict
- `metadata` — caller-provided dict

## IL-4: InProcessEventBus behaviour
- SYNC mode: handlers called in subscription order; publish blocks until all complete
- ASYNC mode: event queued; publish returns immediately
- Subscriber exceptions are caught, logged, and do not affect other subscribers
- Internal diagnostic events must not re-enter the failing handler path

## IL-5: Cycle detection
- Reject events where `propagation_depth >= max_depth` (default 10, configurable)
- Reject events whose `correlation_id` is already active in the current dispatch chain
- Log rejected events with full context

## IL-6: FileEventStore
- Controlled by `event_store.enabled` config key; disabled by default
- Atomic write: write temp file, then rename to final path
- Filename: `{utc_timestamp}_{sanitised_type}_{event_id}.json`
- Persistence failures are logged and must not block publish

## IL-7: ReplayService
- Re-publishes events from store in chronological order
- Sets `is_replay: true` in envelope
- Does not re-persist replayed events
- Supports filter by event type pattern and timestamp range

## IL-8: AsyncQueue
- `queue.Queue`-backed background thread
- Graceful shutdown: drain with configurable timeout (default 30s), log remaining count if timeout exceeded
- V1: events in queue are not persisted to disk; loss on crash is acceptable and documented

## IL-9: Bootstrap contract
- `init_bus()` must be called before any component calls `get_bus()`
- `get_bus()` raises `RuntimeError` if called before `init_bus()`
- `close()` stops the async worker and flushes pending store writes

# Configuration

`.audiagentic/interoperability/config.yaml` — all keys optional, defaults apply if absent:

```yaml
event_store:
  enabled: false
  path: runtime/interoperability/events
  retention_days: 365

async_queue:
  enabled: true
  max_queue_size: 10000
  shutdown_timeout: 30

cycle_detection:
  max_depth: 10
  correlation_tracking: true

source_component: audiagentic
```

# Event Namespace Convention

Event types follow `{component}.{noun}.{verb}` dot notation. Components own their namespace. No schema registry in V1 — document event types in component READMEs.

**Planning namespace (V1 required):**

- `planning.item.state.changed` — payload: `{old_state, new_state}`, metadata subject: `{kind, id}`
- `planning.item.created` — payload: `{label, summary, state}`, metadata subject: `{kind, id}`

**Interop namespace (emitted by bus, internal):**

- `interop.subscriber.failed` — payload: `{pattern, handler_name, error, event_type}`
- `interop.store.write_failed` — payload: `{event_id, error}`

**Knowledge and other namespaces:** defined by those components when they integrate.

# Acceptance Criteria

## AC-1: Protocol contract
- `isinstance(InProcessEventBus(...), EventBusProtocol)` is `True`
- Replacing `InProcessEventBus` with a conforming stub in tests requires zero changes to publishing or subscribing components

## AC-2: Publish and subscribe
- Events delivered to all pattern-matching subscribers in SYNC mode
- ASYNC publish returns before handlers complete
- Wildcard subscriptions match correct single-segment patterns only

## AC-3: Subscriber isolation
- Subscriber exception does not prevent delivery to remaining subscribers
- Bus remains operational after subscriber failure

## AC-4: Envelope
- All auto-generated fields present on every dispatched event
- Emitters pass only `event_type`, `payload`, and optional `metadata`

## AC-5: Cycle detection
- Events at `propagation_depth >= max_depth` are rejected and logged
- Events with repeated `correlation_id` in active chain are rejected and logged

## AC-6: Persistence
- Events written atomically when store enabled
- Persistence failure logged; publish not blocked

## AC-7: Replay
- Replayed events carry `is_replay: true`
- Replay does not create duplicate persistence entries

## AC-8: Bootstrap
- `get_bus()` before `init_bus()` raises `RuntimeError`
- `close()` stops async worker cleanly within shutdown timeout

## AC-9: Planning integration
- `planning.item.state.changed` emitted after every successful state commit
- Existing hook behaviour unchanged during transition period

# Implementation Order

1. task-0257 — package scaffolding: `protocol.py`, `envelope.py`, `exceptions.py`, `config.py`, `adapters/__init__.py`, `__init__.py` with `init_bus`/`get_bus`
2. task-0248 — `InProcessEventBus` in `bus.py`: SYNC dispatch, pattern matching, subscriber isolation, cycle detection
3. task-0264 — `AsyncQueue` in `queue.py`: background worker, ASYNC delivery mode
4. task-0249 — `FileEventStore` in `store.py`: atomic writes, configurable path
5. task-0250 — `ReplayService` in `replay.py`: chronological replay with `is_replay` flag
6. task-0253 — Planning integration: wire `init_bus` at planning bootstrap, emit `planning.item.state.changed`
7. task-0255 — Hook bridge: route compatible hooks through canonical events, legacy hooks remain
8. task-0256 — Integration tests: publish/subscribe, isolation, persistence, replay, bootstrap contract

# Notes

Assessment on 2026-04-17: event-layer spec is largely implemented. Remaining open items are knowledge handler correctness (`task-0261`) rather than basic event-bus integration, plus any intentionally retained follow-up tooling.
