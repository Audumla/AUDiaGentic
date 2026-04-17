---
id: task-0264
label: Implement async event queue for background processing
state: done
summary: Create background worker queue for ASYNC mode event processing
spec_ref: spec-019
request_refs:
- request-17
standard_refs:
- standard-0005
- standard-0006
---







# Description

Implement background worker queue for ASYNC mode event processing. This task owns queuing async events, background processing thread, and ensuring events are not lost during normal operation.

**API:**
```python
# EventBus automatically uses AsyncQueue for ASYNC mode
bus.publish("planning.task.done", {...}, mode=ASYNC)  # returns immediately

# AsyncQueue processes events in background
async_queue.start()  # start background worker
async_queue.stop()   # graceful shutdown
```

**Key behaviors:**
- ASYNC events queued immediately, `publish()` returns in <5ms
- Background worker processes queue continuously (threading-based, not asyncio)
- **V1 crash recovery:** Events in queue lost on crash if `persist_on_checkpoint: false`
- **V2 durability:** Optional disk persistence on checkpoint (configurable)
- Queue drains on shutdown (configurable timeout, default: 30s)
- Thread-safe using `queue.Queue`
- Max queue size with backpressure

# Acceptance Criteria

- ASYNC `publish()` returns in <5ms (queue only, no processing)
- Background worker processes queued events in order (threading-based)
- Queue doesn't lose events during normal operation
- **V1 crash recovery:** Events in queue lost on crash if `persist_on_checkpoint: false` (documented)
- **V2 durability:** Optional disk persistence on checkpoint (configurable)
- Graceful shutdown drains queue (configurable timeout, default: 30s)
- Unit tests cover: queueing, background processing, shutdown behavior
- Smoke test proves ASYNC events are processed correctly

# Notes

Depends on: task-0248 (EventBus). This task is async queue only, not the EventBus itself.
