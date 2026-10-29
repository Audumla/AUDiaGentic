# Gateway observability retention

## Request preparation timings

The core request observation journal also records `preparation-phase` actions
from `session-dispatch`. Read these through the existing observation API (or
the request's `observations.ndjson`); no verbose data is added to compact MCP
status responses. `facts.diagnostic-facts.phase` distinguishes
`default-session-guard`, `management-mcp-catalog`, `session-open`,
`session-rehydrate`, `provider-prepare`, and `transport-open`.

Each span records `begin` followed by `completed` or `failed`, a monotonic
`elapsed-ms`, attempt epoch, request/session identity and hashed owner identity.
Nested phase durations overlap and must not be summed. An unmatched begin
localizes an outstanding operation or process interruption; it does not prove
failure. These observations never renew provider activity or alter inactivity
timeouts. They contain no call arguments, prompt, response or exception text.
They use the same bounded storage and retention as other observations.

Compare admission/claim timestamps in the request timeline with these spans
to distinguish actual queue wait from session preparation. Instrumentation is
available only after the gateway has loaded the updated code; it cannot
reconstruct individual phases for older requests.

## Daily trace segments and five-day retention

Gateway request timelines, session timelines, observations and recovery journals
use an append-only head plus immutable UTC-dated segments. A head rolls when the
UTC day changes or the next record would exceed its configured byte cap. A
single oversized record is kept intact, never truncated. Existing unsegmented
files are adopted on their next write or background maintenance pass.

For example, a request's `observations.ndjson` is the current head;
`observations.ndjson.segments/YYYY-MM-DD.<sequence>.<id>.ndjson.gz` contains
closed data. The small `.rotation.json` sidecar tracks the head's UTC day and
durable segment/event watermarks, so IDs do not restart after raw trace expiry.
Only the current head needs a byte-offset index. Closed segments are streamed
in order, and compression never changes event sequence IDs.

Compression and expiry run on the existing background retention worker, not
the provider response/event loop. The standalone gateway schedules maintenance
at startup and hourly, even if no new request completes. Terminal transitions
also schedule coalesced sweeps. Each pass is bounded by `max-batch-size`.

Closed segments are gzip-compressed losslessly. Eligible timeline/observation segments expire after
**five elapsed days from their last append**, not five days since compression.
Compression preserves that timestamp. An idle old head is rolled by maintenance
so cleanup does not require another provider event. Busy days can have several
size-bounded segments; files are removed whole rather than rewritten repeatedly.

### Protection and scope

Age never authorizes deleting active, unresolved, recovery-required or pinned
evidence. Eligibility is rechecked under lifecycle/retention fences immediately
before removal. Unmatched recovery action intent and unresolved recovery results
also protect the trace, even if the request record lacks a recovery-required
flag. Session traces need a terminal session and no protected linked requests.
Unreadable state, unknown lineage, or invalid retention configuration fails
closed: keep the data.

Pins include durable session lineage and runtime dependencies. Consequently a
five-day setting is **not an unconditional disk-size ceiling**: protected data
can remain longer until its dependency is explicitly resolved/released.

This policy deletes only recognized closed trace segments. Request records,
final and partial response artifacts, provider bindings, and runtime state are
not targets. Recovery-action journals are also durable control state: retry
budgets and idempotency still depend on them after a request finishes. Their
segments rotate and compress, but remain until explicit request/session purge.
The existing 100-request history policy remains separate; its
compaction handles unsegmented historical heads without rewriting newly rotated
journals. Explicit archive/session/request purge retains its own safeguards.
A shared external maintenance fence prevents a late sweep observation from
recreating a request after purge.

The operator `console-trace.log` is separate: it retains its existing bounded
`.1` backup. Redacted observation artifacts retain their own expiry rules.

## Configuration

The machine-owned policy is the `gateway.retention` section of the user settings
(the gateway is shared by every project, so a project's own settings never apply):

```yaml
gateway:
  retention:
    policy_id: ops
    purge_enabled: false
    journal_retention_days: 5
    request_history_limit: 100
    max_batch_size: 100
    timeline_max_bytes: 1048576
    observation_max_bytes: 2097152
    recovery_max_bytes: 1048576
    console_trace_max_bytes: 4194304
```

`journal_retention_days` accepts integers 1-3650. It defaults to five when the
section is absent; a policy that fails validation is logged, is treated as
invalid, and disables automatic trace deletion. This user-authorized trace
cleanup is independent of `purge_enabled`, which governs explicit destructive
request/archive operations. Settings changes are read without a restart. There
are no environment overrides and no separate policy file.
Changing inherited environment overrides, or loading this implementation,
requires a gateway restart.

## Reading retained evidence

Use `agent_task_observations`, request history/diagnostics and recovery-journal
tools as before. They stream retained plain/gzip segments plus the head and
return bounded pages; callers do not have to decompress files or locate paths.
Routine status responses do not grow to include the trace.

The privileged `agent_gateway_get_retention_policy` tool reports effective
trace age, rotation/compression mode, rolling history count and byte caps.
A null trace age means automatic expiry is disabled by invalid configuration.
It never returns policy paths, request contents, or provider data. Expired raw
traces cannot be retrieved; request outcome and final-response retrieval remain
independent.
