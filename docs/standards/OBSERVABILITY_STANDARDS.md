# Observability Standards

## Durable Resource Timelines

Components that own long-running or asynchronous resources must write an
append-only `timeline.ndjson` beside the durable resource record.

Use `audiagentic.foundation.observability.record_timeline_event` instead of
component-local JSONL writers.

Timeline events must include:

- `component`: owning component id
- `resource-kind`: stable resource type
- `resource-id`: durable id
- `correlation-id`: session/request correlation id when available
- `event`: dot-style milestone name
- `state`: current state when applicable
- `attributes`: small structured context, redacted by the caller before write

Milestones should cover:

- resource creation
- queue admission/rejection
- state transitions
- attempt start and finish
- cancellation request
- terminal outcome

Do not persist raw secrets, stdout/stderr dumps, or unredacted exception text in
timeline attributes.

If a component receives event metadata with `correlation_id`, propagate it into
timeline events. Otherwise `record_timeline_event` falls back to the active
logging correlation context.

## Relationship To Events And Logs

Event bus messages notify other components. Timelines explain what happened for
one resource after the fact. Use both when a resource lifecycle must be both
reactive and debuggable.

Regular `logger` calls remain useful for operator diagnostics, but must not be
the only durable observability surface for async resource state.
