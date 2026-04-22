---
id: task-245
label: Implement InProcessEventBus satisfying EventBusProtocol
state: done
summary: 'Implement InProcessEventBus in bus.py satisfying EventBusProtocol: SYNC/ASYNC
  dispatch, single-segment wildcard pattern matching, subscriber isolation, cycle
  detection via propagation_depth and correlation_id'
spec_ref: spec-23
request_refs:
- request-17
standard_refs:
- standard-5
- standard-6
---














# Description

Implement the core in-process `EventBus` for the interoperability layer. This task owns synchronous and asynchronous publish/subscribe, subscription registry, wildcard pattern matching, unsubscribe support, subscriber isolation, event envelope generation, and **cycle detection via propagation_depth limits**.

**Core API:**
```python
# Explicit dependency injection (preferred)
bus = EventBus()
handle = bus.subscribe("planning.task.*", handler)

# Or singleton for bootstrap convenience
from audiagentic.interoperability import EventBus
bus = EventBus.get_instance()
```

**Key behaviors:**
- SYNC mode: blocks until all subscribers complete
- ASYNC mode: returns immediately, events processed by background worker (task-0264)
- Registration order: subscribers invoked in subscription order
- **Wildcard patterns:**
  - `*` matches exactly one segment (e.g., `planning.task.*` matches `planning.task.done`)
  - `**` matches zero or more segments (e.g., `planning.**` matches all planning events)
- Subscriber isolation: one failure doesn't affect others
- Envelope generation: auto-generate `id`, `occurred_at`, `source_component`, `is_replay`, `propagation_depth`
- **Cycle detection: reject events with `propagation_depth >= 10` or `correlation_id` in current chain**

# Acceptance Criteria

- `EventBus.publish(event_type, payload, metadata=None, mode=SYNC)` delivers to all matching subscribers (blocking)
- `EventBus.publish(event_type, payload, metadata=None, mode=ASYNC)` returns immediately (non-blocking)
- `EventBus.subscribe(pattern, handler)` returns `SubscriptionHandle`
- `EventBus.unsubscribe(handle)` removes subscriber
- Wildcard `planning.task.*` matches `planning.task.done` but not `planning.task.subtask.done`
- Subscriber exceptions logged but don't crash bus or affect other subscribers
- Event envelope includes: `id`, `type`, `version`, `occurred_at`, `source_component`, `payload`, `metadata`, `is_replay`, `propagation_depth`
- **Events with `propagation_depth >= 10` rejected and logged**
- **Events with `correlation_id` in current chain skipped and logged**
- Unit tests cover: SYNC/ASYNC delivery, wildcard matching, unsubscribe, subscriber failure isolation, cycle detection
- Smoke test proves EventBus imports and basic publish/subscribe works

# Notes

Persistence is task-0249, replay is task-0250, async queue is task-0264. This task is in-memory bus with cycle detection.
