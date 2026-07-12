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

## Operational Sidecar Records

Operational sidecar records are cross-cutting, append-only ndjson files that
capture events spanning multiple resources or components (e.g., dead-letter
queues, trigger audit trails). They are distinct from per-resource timelines:
- **Dead-letter queue:** `.audiagentic/runtime/agent-jobs/dead-letter.ndjson` —
  durable record of failed async event-handler firings. Written via
  `write_dead_letter` (see ARCHITECTURE_STANDARDS §14 Async Event Handling).
  Each entry carries correlation context sufficient for manual replay. Consumed
  by EDJ02 (step 5), EDJ04 (step 5), and EDJ05 (notes).

- **Timelines** (`record_timeline_event`) — per-resource history. Each file
  tracks the lifecycle of one resource kind+id pair. Best-effort writes that
  do not break primary mutations.

- **Operational sidecar records** (`append_operational_record`) — cross-cutting,
  structured operational log for a subsystem (e.g., all dead-letter events,
  all trigger activations). O(1) append semantics with per-path threading locks.

Both surfaces require:

- A `correlation_id` field to link related records across traces.
- Redaction of sensitive content before write (no raw prompts, outputs, secrets).

### Using operational sidecar records

Use `audiagentic.foundation.observability.append_operational_record` for any
append-only operational ndjson log that is not a per-resource timeline. The helper:

1. Enforces `correlation_id` presence at the boundary (raises VAL-OPR-001 if absent).
2. Rejects denylisted fields (`prompt-body`, `output`, `prompt_body`, `raw_output`)
   with CON-OPR-002 — keeps sensitive data out of sidecar logs.
3. Injects an ISO-8601 timestamp if the record lacks one.
4. Creates parent directories automatically.
5. Uses per-path threading locks to prevent interleaved writes within a process.

Do not use this helper for rotation, retention, or framework-style record schemas —
it is an append-and-guard primitive. Multi-process locking is out of scope.
