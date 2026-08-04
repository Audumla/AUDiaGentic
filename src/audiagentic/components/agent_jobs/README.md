# components/agent_jobs/

## Purpose
The active core of job orchestration. Contains all modules that drive a prompt request through the full agent job lifecycle.

## Ownership
- Prompt parsing and request normalization
- Job state machine transitions
- Packet execution and result collection
- Job control (cancel, stop, kill)
- Approval and review orchestration
- `contracts/`: Job, stage, approval, review, and prompt JSON Schema definitions

## Must NOT Own
- Job record I/O (→ `runtime/state/jobs_store.py`)
- Session input I/O (→ `runtime/state/session_input_store.py`)
- Review bundle I/O and validation
- Provider-specific execution code (→ `interoperability/providers/adapters/`)

## Allowed Dependencies
- `foundation/contracts` — errors, schemas, canonical IDs
- `foundation/config` — provider config, project config
- `runtime/state` — jobs_store, session_input_store
- `interoperability/providers` — provider selection and dispatch
- `interoperability/protocols/streaming` — stream sink management

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `prompt_launch.py` | Entry point: parse and launch a prompt request |
| `prompt_parser.py` | Normalize raw prompt text into a structured request |
| `state_machine.py` | Job state transitions and lifecycle enforcement |
| `packet_runner.py` | Execute a single job packet against a provider |
| `control.py` | Job control requests (cancel, stop, kill) |
| `approvals.py` | Approval workflow and review orchestration |
| `reviews.py` | Build and validate review reports and bundles |
| `records.py` | Job record construction (not persistence) |
| `profiles.py` | Workflow profile loading and application |
| `prompt_syntax.py` | Prompt syntax parsing and validation |
| `prompt_templates.py` | Prompt template management |
| `stages.py` | Job stage definitions and orchestration |
| `event_triggers.py` | Event-trigger config load/validation and filter evaluation |
| `event_observer.py` | Bus subscription, trigger firing, trigger audit, outcome propagation |
| `event_overview.py` | Read-only operator aggregation over audit + job records |
| `dead_letter.py` | Durable redacted records for failed async handlers |

## Event-driven jobs

Configured event-bus triggers launch durable agent jobs whose prompts are
dispatched to the agents execution gateway **asynchronously**. There is no blocking
path: a trigger firing returns nothing to the publisher — outcomes come back
as `agents.execution.*` lifecycle events and are applied to job state.

### Flow (implemented modules)

1. **Config** — `event_triggers.py` loads
   `.audiagentic/config/agent-jobs/event-triggers.yaml`, validating each
   trigger against `contracts/event-trigger.schema.json` (component-only
   schema; no foundation mirror). Every schema-valid trigger is returned,
   including `enabled: false` ones — suppression happens at firing time so it
   is auditable.
2. **Subscription** — `event_observer.py` subscribes once per configured
   trigger (triggers sharing an event pattern each get their own
   subscription) plus the four gateway outcome topics. Activation is
   lifecycle-driven via the component descriptor (`lifecycle-observer`).
3. **Firing** — on a matching event the observer resolves/creates a
   `correlation_id`, suppresses disabled triggers (audit `status=suppressed`)
   and filter misses (audit `status=suppressed`, `reason=filter`), then
   builds a durable job record with event provenance (`event-source` block,
   `launch-source.surface = "event"`), renders the prompt through the shared
   context pipeline (`prompt_context.py` + `foundation/templates.py`), and
   transitions the job created → ready → running.
4. **Dispatch** — the observer PUBLISHES `agents.execution.gateway.requested` with
   `source: "event-trigger:<trigger-id>"`. Gateway access is events-only:
   agent-jobs never imports `agents_gateway_api`.
5. **Outcomes** — `agents.execution.completed/failed/rejected/cancelled` map to job
   states completed/failed/failed/cancelled. Matching is via metadata
   `job-id` only (the artifact-request-id fallback was not implemented — an
   accepted deviation). Outcomes for terminal jobs are ignored idempotently;
   outcomes for pre-dispatch jobs (created/ready) are refused, dead-lettered,
   and never transition the job.
6. **Failure** — any dispatch failure after job creation transitions that job
   to `failed` (timeline entry carries only the error code) and dead-letters
   the original error via `dead_letter.py` with structurally summarized,
   redacted content (`foundation/logging/redaction.py`). Bus handlers never
   raise.
7. **Cancellation (reverse path)** — cancelling a job whose record carries a
   `gateway-request` artifact publishes `agents.execution.gateway.cancel-requested`
   (topic owned by `agents/agents_gateway_events.py`), which cancels the
   owning gateway request. Publish failure is dead-lettered; the local
   cancellation is never rolled back.

Direct launches (CLI/MCP/API through `prompt_launch.py`) share the same
context/render pipeline: one pipeline, two entry points. A template-free
inline prompt body passes through byte-identical.

### Worked example: planning item creation

`.audiagentic/config/agent-jobs/event-triggers.yaml` (this exact example is
parsed against the shipped schema by
`tests/unit/jobs/test_event_triggers.py::TestReadmeExample`):

```yaml
triggers:
  - contract-version: v1
    trigger-id: plan-item-review
    kind: event
    enabled: true
    event-pattern: planning.item.created
    execution-profile-id: reviewer-default
    workflow-profile: standard
    filter:
      payload.priority: [P0, P1]
    prompt-template: |
      Review the new planning item {event.payload.item_id}
      for project {project.id} (job {job.id}).
```

`filter` supports scalar equality and list membership on dotted paths over
`{payload, metadata}`; clauses AND. No comparisons, regex, or boolean
composition — by design.

### Job records vs gateway request records

- **Job record** (`.audiagentic/runtime/jobs/<job-id>/job.json`) — the
  durable unit of work agent-jobs owns: state machine, approvals, packet,
  event provenance. Agent-jobs owns durable work.
- **Gateway request record** (owned by the `agents` component) — one agent
  execution request: profile, attempts, provider outcome. Agents own profile
  execution. The two are joined by `job-id` in gateway metadata and the
  `gateway-request` artifact on the job.

### Correlation chain

Inbound `correlation_id` (or one generated at firing) flows:
event metadata → job `event-source.correlation-id` → gateway request
metadata → every `agents.execution.*` lifecycle event → job timeline entries.
Join keys: `job-id` / `correlation_id` / `trigger-id` / `request-id`.

### Inspection points

| Where | What |
| ------ | ---- |
| `.audiagentic/runtime/agent-jobs/trigger-audit.ndjson` | one entry per firing: `status` fired/suppressed/failed (+ `reason` for filter suppressions) |
| `.audiagentic/runtime/agent-jobs/dead-letter.ndjson` | redacted records for failed handlers (`payload_summary`, allowlisted `metadata`, per `dead_letter.py`'s required-keys set) |
| `.audiagentic/runtime/jobs/<job-id>/job.json` + `timeline.ndjson` | durable job state and canonical timeline events |
| gateway request record + timeline (agents component) | per-request execution detail |
| `event_jobs_overview` MCP tool (`jobs_mcp.py`) | per-trigger counts, event-job states, 5 most recent failures |
| `agent_task_gateway_overview` MCP tool (agents) | gateway-side request counts and queue depths |

Sidecar record semantics (append-only ndjson, redaction rules, event vs log
roles) are defined in `docs/standards/OBSERVABILITY_STANDARDS.md` — not
restated here.
