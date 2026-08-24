# Agents Component

Agent composition — prompts, roles, execution profiles, agent definitions, and
triggers are stored together in the machine-global
`~/.audiagentic/config/agents.yaml` document and resolved at admission time.
The project marker contains runtime records only; it is not an agent
definition authority.

## Architecture

- `models.py` — ExecutionProfile dataclass, ExecutionProfileStore, validation
- `agents_paths.py` — Path resolution for canonical Agent config and runtime data
- `agents_api.py` — Pure-logic CRUD API (load, save, list, get, create, update, delete, resolve), agent_status status-hook
- `mcp/config_mcp.py` — Canonical Agents configuration MCP server (operator-side only)
- `mcp/runtime_mcp.py` — Canonical Context/Work runtime MCP server (operator-side only)
- `mcp/gateway_mcp.py` — Agent Execution Gateway MCP server (provider-facing)
- `mcp/admin_mcp.py` — Privileged gateway administration MCP server (operator-side only)
- `agents_gateway_store/` — Gateway request/result record contract and persisted state (AG08), split into _shared,_admission, _records,_transitions (SH18)
- `agents_gateway_queue.py` — Per-profile FIFO queue, concurrency limiting, cancel, wait, lifecycle events (AG09)
- `agents_gateway_dispatch.py` — Provider dispatch, retry, fallback (AG10)
- `agents_gateway_session_dispatch.py` — Sessionful dispatch path extracted from dispatch.py (SH18)
- `agents_gateway_turn_events.py` — Turn-event projection and publishing extracted from sessions.py (SH18)
- `agents_gateway_api.py` — Public submit/status/wait/cancel/run API (AG11)
- `agents_gateway_mcp.py` — Gateway MCP server (AG11)
- `agents_gateway_events.py` — Event-triggered submission via `agents.execution.gateway.requested` (AG12)
- `agents_gateway_application.py` — Framework-neutral gateway application contract
- `agents_gateway_service_application.py` — Closed standalone v1 operation/lease router
- `agents_gateway_http_transport.py` — Authenticated IPv4-loopback HTTP adapter
- `agents_gateway_remote_client.py` — Explicit standalone client with bounded attach semantics
- `agents_gateway_service_host.py` — Foundation managed-service host composition; also the sole caller of `runtime/bootstrap/gateway_service_composition.py`'s second composition root (AS60 step 7 / RV888), which composes the shared-gateway execution-profile registry as install/uninstall around this host's own construction/close

## MCP surface split

Configuration (`ag-agents-config`, propagate: `audiagentic`) handles Agent
composition CRUD. Privileged Gateway administration is isolated on
`ag-agents-admin`.
Operational (`ag-agents-gateway`, propagate: `providers`) exposes `agent_task_submit`
and status/cancel/session management to provider CLIs during job execution.

## Error codes

- `VAL-EXP-001` — Profile validation failures
- `VAL-EXP-004` — Unsupported profiles contract version
- `RES-EXP-001` — Profile not found
- `RES-EXP-002` — Duplicate profile ID
- `RES-EXP-003` — No default profile
- `IO-EXP-001` — Failed to read profiles file
- `IO-EXP-002` — Failed to write profiles file

## Agent Execution Gateway

A queued, concurrency-limited dispatch layer that resolves an execution profile
to a provider/model and executes provider work through
`providers.services.execution.execute_provider`, with retry and
cross-profile fallback. Deliberately built on its own request/result
contract rather than agent-jobs' `JobRecord` — see [AG07](../../../../docs/planning/completed/agents/AG07.md)
for why (packet/workflow-profile/approvals/review-policy don't fit a
gateway request).

**What `output` actually contains depends on the provider.** For most execution
profiles (any CLI-based provider — claude, codex, aider, etc.), a gateway
request runs a full provider CLI/session invocation and `output` is that
session's stdout, not a raw chat completion — the claude adapter, for
example, wraps the prompt in an execution envelope and injects packet-document
context before invoking the CLI. Only API-style providers (`local-openai`,
any OpenAI-compatible HTTP endpoint) behave like a direct chat completion.
Don't assume `output` is a clean model response unless the resolved profile's
provider is one of the API-style ones.

Persisted at `.audiagentic/runtime/agent-execution-gateway/<request-id>/record.json`,
validated against `agent-execution-record.schema.json`.

### Request modes

- **Async** (default, and the only mode exposed over MCP) - `agent_task_submit`
  (the sole MCP submission surface, AS63) returns `{request-id, state: "queued"}`
  immediately. Poll `agent_task_status(request_id)` until the request reaches
  a terminal state. Blocking submit-and-wait remains available through the
  underlying Python API, not as an MCP tool.
  Direct execution_profile_id submission bypassing Agent Definition
  resolution is not exposed over MCP — use the Python API layer
  (`GatewayClient.submit_execution_request`) for that.
- **Blocking** (Python API only, not exposed over MCP) — `submit_execution_request(...,
  mode="blocking")` / `run_execution_request(...)` / `GatewayClient.submit_execution_request(...,
  mode="blocking")` submit and wait for a terminal result or timeout in one call, with
  no transport-imposed cap — for in-process callers only (e.g. a supervisor holding its
  own thread for a long task, RV511).
- **Event-triggered** — publish `agents.execution.gateway.requested` on the foundation event bus
  (`{project-root, prompt-body, execution-profile-id?, blocking?, source?}`).
  Always async unless `payload.blocking` is explicitly set. Not for one-shot MCP-tool use —
  use `agent_task_submit` and poll `agent_task_status` for that.

### State model

`queued -> running -> completed | failed | cancelled` (or `queued -> rejected` when the
per-profile queue is full). See `workflows.yaml`'s `gateway-request` kind for the full
transition table. `cancel-requested` is a separate persisted flag, not a state — cancelling
a queued request transitions it straight to `cancelled`; cancelling a running request only
records intent (the dispatch retry loop checks it between attempts and stops, but a
request that finishes normally before the next check completes as `completed`, not `cancelled`
— cancellation of an in-flight provider call is best-effort, not interruptive).

### Params (execution profile `params` block)

All optional, all validated (a present-but-invalid value raises rather than silently
defaulting) — resolved via `agents_gateway_queue.resolve_*` / `agents_gateway_dispatch.resolve_retry_count`:

- `max-concurrency` (int, default 1) — concurrent in-flight requests per profile.
- `queue-max-size` (int, default `max(8, max_concurrency*2)`) — requests rejected once exceeded.
- `global-capacity` (int or `unlimited`, optional) — explicit gateway-wide overlay;
  when omitted, legacy `virtual-capacity`/`max-concurrency` behavior remains.
- `project-capacity` (int or `unlimited`, optional) — active turns allowed per
  canonical project root. Missing means unlimited.
- Persistent sessions have no configurable capacity dimension. The queue keeps
  one in-flight turn per durable session for correctness, while
  `project-capacity` limits active provider tasks for the canonical project.
- `retry-count` (int, default 1) — additional attempts after a transient failure, per profile.
- `session-turn-timeout-seconds` (number, default 0 = disabled) — optional
  explicit absolute deadline for one session turn. Activity observations do
  not extend an enabled absolute ceiling; GPT-auto uses its provider-owned
  response ceiling instead of a competing Gateway turn timer.
- `session-turn-silence-timeout-seconds` (number, default 0 = disabled) —
  opt-in in-turn liveness watchdog: if a running turn produces no transport
  events for this long, the reaper fails the session with close-reason
  `turn-silence-timeout`. This is configured timeout policy, not proof of
  process death or orphaning. Only enable for harnesses with a known event cadence.

Cancelling a running SESSION request now also signals protocol-level
`session/cancel` to the in-flight turn (best-effort); an interrupted turn
terminalizes the request as `cancelled` while the session stays usable.
Non-session requests keep the between-attempts cooperative check only.

### Lifecycle events

Published by `agents_gateway_queue` for *every* request regardless of origin (MCP or event):
`agents.execution.queued`, `agents.execution.started`, `agents.execution.completed`, `agents.execution.failed`,
`agents.execution.cancelled`, `agents.execution.rejected`. Base payload: `{request-id, execution-profile-id,
state}`; terminal events (`completed`/`failed`/`cancelled`/`rejected`) additionally carry
`provider-id`, `model-id`, `error`, and `attempt_count` so an observer can tell what happened
without reading `record.json`. `correlation_id`/`subject` are preserved automatically — they
flow from the triggering request's `metadata` through to every lifecycle event for that request.
Publish never raises even if the event bus or a subscriber misbehaves — a broken observer
must never prevent a request from reaching its real terminal state.

### Restart reconciliation

`GatewayQueueManager` is an in-process singleton. A restarted host cannot recover
the old worker's execution state. Shared-gateway recovery is owned by the SH07
active-work index: `agents_gateway_recovery.recover_gateway_requests(...)`
releases stale queued claims and interrupts stale running claims only when the
recorded service owner epoch is no longer live. The public gateway API does not
perform a second project-wide orphan sweep.

### Explicit standalone mode (SH04)

Start a local service explicitly:

```text
audiagentic gateway serve --host 127.0.0.1 --port 8765 --token-file <private-path>
```

Clients opt in with all three settings; there is no discovery or in-process
fallback in this phase:

```text
AUDIAGENTIC_GATEWAY_MODE=standalone
AUDIAGENTIC_GATEWAY_ENDPOINT=http://127.0.0.1:8765
AUDIAGENTIC_GATEWAY_TOKEN_FILE=<private-path>
```

The service rejects non-loopback origins, missing/incorrect tokens, protocol
version mismatches, stale owner epochs, inactive leases, and non-canonical
project roots before domain work. Health may retry one transient network
failure. Domain mutations are never network-retried; the client can reattach
once only after the service proves the previous lease was stale before
invocation. Select `AUDIAGENTIC_GATEWAY_MODE=in-process` to roll back during
the migration.

### Self-managed automatic mode (SH05)

Set `AUDIAGENTIC_GATEWAY_MODE=automatic` to request the compatible machine-wide
gateway. The public gateway client delegates the single-winner start-or-attach
race, detached process ownership, stale-record recovery, readiness, and initial
client lease to the foundation managed-service lifecycle. The optional
`AUDIAGENTIC_GATEWAY_PORT` selects the loopback port (default `8765`).

Health reports `lifetime-scope`, and the automatic client exposes the same
foundation evidence as `service_lifetime_scope`. `shared-service-host` means
the service detached from its starter. On a Windows supervisor whose Job
Object denies breakaway, foundation reports `session-child`: the gateway is
shared while that supervisor remains alive but may exit when its Job Object
closes. That degradation is logged and observable; it is never presented as a
fully detached owner.

Automatic mode does not fall back to the in-process gateway. An incompatible
live protocol, unprovable process owner, or unhealthy startup is reported as a
managed-service error; an unrelated live process is never terminated. This
mode remains opt-in until the SH11 consumer cutover.

### Dashboard recent window

The loopback dashboard serves only records in the configured recent activity
window. Set `AUDIAGENTIC_GATEWAY_DASHBOARD_RECENT_SECONDS` in the gateway
process to change the default (12 hours; maximum 30 days). Active requests and
live sessions remain visible even when idle beyond that window. The dashboard
can temporarily override the gateway default with `?recent-seconds=<n>` or its
Recent window control; the override affects only that dashboard view.

### Durable trigger ingress (SH09)

Cross-process gateway triggers use a durable file spool beside the service
record (`<service-root>/ingress/`), not the in-process event bus and not a
broker. Publish from any process with
`agents_gateway_ingress.publish_gateway_trigger(topic, payload)` — safe while
the service is down; the running host drains the spool at startup and every
second thereafter. Spool `event-id` becomes the request idempotency key, so
redelivery replays the original request instead of double-dispatching.
Malformed or validation-rejected events move to `ingress/dead-letter/`
(replayable via `replay_dead_letter`); transient failures retry in order with
a bounded attempt budget.

### Self-managed lifecycle (SH10)

`AUDIAGENTIC_GATEWAY_IDLE_GRACE_SECONDS` (unset/0 = keep-warm forever)
enables idle self-shutdown: a running service with no active client leases,
no queued/running work, no live sessions, and an empty ingress spool for one
full grace window drains and exits through the PR06 guarded transitions
(running → draining → re-check → stopped). A lease acquired during the grace
window resets it. Operators get `service_status` / `service_drain` /
`service_resume` / `service_stop {force}` as closed service operations
(force reports the work it abandons). A dead-or-unprovable recorded owner is
recovered record-only via `agents_gateway_lifecycle.recover_unprovable_owner`
(explicit confirm required; preserves diagnostics; never signals the PID).

### Known limitations

- **Not project-scoped**: the queue manager singleton is process-wide, not keyed by
  project-root. Fine in practice (one project per process), but worth knowing.
- **Recovery boundary**: SH04 proves explicit service ownership, client-exit
  survival, and deterministic idle process restart. Durable recovery of queued
  or running work after service-process failure is owned by SH07 active-work
  recovery; session orphan/death handling continues through the session runtime
  and AS26 process-evidence path.
- **Automatic mode is not yet the default**: SH11 owns consumer cutover and
  removal of in-process ownership. SH04 standalone and SH05 automatic modes
  remain explicit migration choices.

