# Event Standards

This document defines the event schema, naming conventions, and lifecycle for the AUDiaGentic event system.

## Event Schema

All events follow this schema:

```python
EventEnvelope(
    event_id: str,           # Unique identifier (UUID)
    event_type: str,         # Event type (e.g., "planning.item.created")
    timestamp: datetime,     # ISO 8601 timestamp with timezone
    payload: dict,           # Event-specific data
    metadata: dict,          # Cross-cutting concerns
)
```

### Payload Structure

Event payloads should include:
- `id`: The ID of the affected item (if applicable)
- `kind`: The kind of item (task, wp, plan, spec, request, standard)
- Event-specific fields (see event registry)

### Metadata Structure

Standard metadata fields:
- `triggered_by`: "manual" or "automatic"
- `correlation_id`: UUID for tracing related events
- `propagation_depth`: Integer for cycle detection (0-10)
- `is_replay`: Boolean, true if event is from replay

## Naming Conventions

Event types follow the pattern: `{domain}.{entity}.{action}.{context}`

### Domains

- `planning`: Planning component events
- `knowledge`: Knowledge component events
- `system`: Cross-component system events

### Entities

- `item`: Generic planning item (task, wp, plan, spec, request, standard)
- `claim`: Claim management events
- `index`: Index operations

### Actions

- `created`: Item created
- `updated`: Item updated (non-state changes)
- `deleted`: Item deleted
- `state.changed`: State transition occurred
- `state.will-change`: State transition about to occur

### Examples

- `planning.item.created`
- `planning.item.updated`
- `planning.item.state.changed`
- `planning.item.deleted`
- `planning.reconciled`

## Event Lifecycle

### 1. Event Creation

Events are created by the source component:

```python
bus.publish(
    event_type="planning.item.created",
    payload={"id": "task-0001", "kind": "task"},
    metadata={"triggered_by": "manual"}
)
```

### 2. Event Delivery

Events are delivered via the EventBus:
- **Async mode** (default): Events queued for background processing
- **Sync mode**: Events processed immediately

### 3. Event Storage

All events are stored in `FileEventStore`:
- Location: `.audiagentic/events/`
- Format: JSON per event
- Indexed by timestamp for replay

### 4. Event Replay

Events can be replayed via `ReplayService`:
- Replayed events have `is_replay: true` in metadata
- Consumers should skip replayed events unless opt-in

## Consumer Guidelines

### Subscription

Subscribe to events using wildcards:

```python
bus.subscribe("planning.item.*", handler)  # All item events
bus.subscribe("planning.item.state.*", handler)  # State events only
```

### Handler Signature

Event handlers should follow this signature:

```python
def handler(event_type: str, payload: dict, metadata: dict) -> None:
    # Skip replayed events
    if metadata.get("is_replay"):
        return
    
    # Process event
    ...
```

### Error Handling

Handlers should:
- Catch and log exceptions
- Not re-raise exceptions (to avoid breaking event pipeline)
- Use `logger.warning()` for recoverable errors

## Propagation Guidelines

### State Propagation

State changes propagate up the hierarchy:
- Task → WP → Plan → Spec

### Propagation Rules

1. **All children done → Parent done**
2. **Any child blocked → Parent blocked** (unless parent is terminal)
3. **Any child in_progress → Parent in_progress** (if parent is ready)

### Cycle Prevention

- Track `propagation_depth` in metadata
- Stop propagation at depth 10
- Use `correlation_id` to trace propagation chains

## Event Registry

The canonical event registry is maintained in `.audiagentic/interoperability/events.yaml`.

All events must be registered before use.

## Best Practices

1. **Keep payloads minimal**: Only include essential data
2. **Use metadata for cross-cutting concerns**: Don't clutter payload
3. **Be idempotent**: Handlers should handle duplicate events gracefully
4. **Log important events**: Use propagation log for state changes
5. **Test with replay**: Ensure handlers work correctly with replayed events
