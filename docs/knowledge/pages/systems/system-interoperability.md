## Summary
The AUDiaGentic interoperability system provides event bus infrastructure and cross-component communication. It enables loose coupling between planning, execution, runtime, and knowledge components through publish-subscribe messaging, event replay, and state synchronization.

## Current state
**Interoperability System** (`src/audiagentic/interoperability/`):

**Event Bus:**
- **Queue** (`queue.py`): Event queue management with delivery modes
- **Store** (`store.py`): Persistent event storage and retrieval
- **Replay** (`replay.py`): Event replay for recovery and testing

**Provider System** (`src/audiagentic/interoperability/providers/`):
- **Adapters** (`adapters/`): Provider-specific implementations (codex, cline, claude, gemini, qwen, opencode)
- **Execution** (`execution.py`): Provider dispatch
- **Selection** (`selection.py`): Provider selection logic
- **Health** (`health.py`): Provider health checks
- **Models** (`models.py`): Model catalog types
- **Status** (`status.py`): Provider status reporting

**Streaming Protocols** (`src/audiagentic/interoperability/protocols/streaming/`):
- **Provider Streaming** (`provider_streaming.py`): Command execution
- **Sinks** (`sinks.py`): Stream sinks (InMemorySink, ConsoleSink, RawLogSink, NormalizedEventSink)
- **Completion** (`completion.py`): Result normalization

**Delivery Modes:**
- **SYNC**: Synchronous delivery (blocking)
- **ASYNC**: Asynchronous delivery (non-blocking)
- **PERSISTENT**: Persistent delivery (stored and replayable)

**Core Capabilities:**
- Event publishing: publish events to the bus
- Event subscription: subscribe to event types
- Event filtering: filter events by type, payload, metadata
- Event persistence: store events for replay
- Event replay: replay events from checkpoint
- Delivery modes: sync, async, persistent delivery

**Event Types:**
- `planning.item.state.changed`: Planning item state transitions
- `planning.item.created`: New planning artifacts
- `execution.job.started`: Job execution started
- `execution.job.completed`: Job execution completed
- `runtime.state.updated`: Runtime state changes
- `knowledge.page.synced`: Knowledge pages synchronized

**Integration Points:**
- Planning system: publishes state changes
- Execution system: publishes job events
- Runtime system: publishes state updates
- Knowledge component: subscribes to all events for sync

**Provider Architecture:**

**Design Principles:**
1. **Modularity**: Each provider isolated to its own adapter file
2. **Separation of Concerns**: Shared code is generic; provider-specific code is isolated
3. **Schema Validation**: All configuration validated against JSON schemas
4. **Test Coverage**: Comprehensive testing for each component

**Provider Isolation:**
Each provider has its own file in `interoperability/providers/adapters/`:
- `codex.py` (~350 lines): Codex-specific with milestone parsing
- `cline.py` (~330 lines): Cline-specific with NDJSON parsing
- `claude.py` (~345 lines): Claude-specific with stream-json parsing
- `gemini.py` (~340 lines): Gemini-specific with plain text output
- `qwen.py` (~275 lines): Qwen-specific with plain text output
- `opencode.py` (~330 lines): opencode-specific with NDJSON parsing

**Provider Implementation Pattern:**
Each provider implements:
1. **Event extractor**: Parses provider-specific output format
2. **Stream builder**: Configures sinks for that provider
3. **Completion parser**: Extracts structured results

All using the same shared interfaces from `protocols/streaming/`.

**Shared Components (Provider-Agnostic):**
- `StreamSink` protocol: Stream output interface
- `InMemorySink`, `ConsoleSink`, `RawLogSink`, `NormalizedEventSink`: Sink implementations
- `run_streaming_command()`: Command execution
- `ProviderCompletion`: Result normalization
- `validate_provider_config()`: Config validation

**Configuration:**
Provider configuration in `.audiagentic/providers.yaml` validated against `provider-config.schema.json`:

```yaml
providers:
  <provider-id>:
    enabled: boolean
    install-mode: string
    access-mode: enum
    default-model: string
    timeout-seconds: integer
    execution-policy:
      output-format: enum
      permission-mode: enum
      safety-mode: enum
      auto-approve: boolean
      full-auto: boolean
```

## How to use
**Event Publishing:**

```python
from audiagentic.interoperability import get_bus, DeliveryMode

## Get event bus instance
bus = get_bus()

## Publish event (async)
bus.publish(
    event_type="planning.item.state.changed",
    payload={
        "item_id": "task-0001",
        "old_state": "ready",
        "new_state": "in_progress"
    },
    metadata={"timestamp": "2026-04-17T03:00:00Z"},
    mode=DeliveryMode.ASYNC
)

## Publish event (persistent)
bus.publish(
    event_type="execution.job.completed",
    payload={
        "job_id": "job-123",
        "status": "success",
        "duration_ms": 5000
    },
    mode=DeliveryMode.PERSISTENT
)
```

**Event Subscription:**

```python
from audiagentic.interoperability import get_bus

## Get event bus instance
bus = get_bus()

## Define event handler
def on_state_change(event):
    print(f"State changed: {event.payload}")
    # Handle state change

## Subscribe to event type
subscription = bus.subscribe(
    event_type="planning.item.state.changed",
    handler=on_state_change
)

## Unsubscribe
bus.unsubscribe(subscription)

## Subscribe with filter
subscription = bus.subscribe(
    event_type="execution.job.completed",
    handler=on_job_complete,
    filter={"status": "success"}
)
```

**Event Persistence and Replay:**

```python
from audiagentic.interoperability import get_store, replay

## Get event store
store = get_store()

## Store event
store.store_event(
    event_type="planning.item.created",
    payload={"item_id": "task-0001"},
    metadata={"created_at": "2026-04-17T03:00:00Z"}
)

## Retrieve events
events = store.get_events(
    event_type="planning.item.state.changed",
    since="2026-04-17T00:00:00Z"
)

## Replay events from checkpoint
replay.from_checkpoint(
    checkpoint_id="checkpoint-123",
    handlers={
        "planning.item.state.changed": on_state_change,
        "execution.job.completed": on_job_complete
    }
)

## Replay all events
replay.all(
    handlers={
        "planning.item.state.changed": on_state_change
    }
)
```

**Component Integration:**

```python
# In planning component
from audiagentic.interoperability import get_bus

def on_state_change(item_id, old_state, new_state):
    bus = get_bus()
    bus.publish(
        event_type="planning.item.state.changed",
        payload={
            "item_id": item_id,
            "old_state": old_state,
            "new_state": new_state
        },
        mode=DeliveryMode.PERSISTENT
    )

# In knowledge component
from audiagentic.interoperability import get_bus

def setup_event_subscriptions():
    bus = get_bus()
    bus.subscribe(
        event_type="planning.item.state.changed",
        handler=handle_planning_state_change
    )
    bus.subscribe(
        event_type="execution.job.completed",
        handler=handle_job_completion
    )
```

**Workflow:**
1. Components publish events on state changes
2. Events stored in persistent queue
3. Subscribed components receive events
4. Events can be replayed for recovery
5. Checkpoints enable selective replay

## Sync notes
This page should be refreshed when:
- New event types are added
- Delivery modes are modified
- Event schema changes
- New interoperability features are introduced
- New providers are added or existing providers are modified
- Provider configuration schema changes

**Sources:**
- `src/audiagentic/interoperability/` - Interoperability implementation
- `src/audiagentic/interoperability/providers/` - Provider implementations
- `src/audiagentic/foundation/config/` - Provider configuration
- Event type definitions in component modules
- Event bus configuration
- Provider configuration schemas

**Sync frequency:** On interoperability or provider system changes

## References
- [Planning System](./system-planning.md)
- [Execution System](./system-execution.md)
- [Runtime System](./system-runtime.md)
- [Knowledge System](./system-knowledge.md)
