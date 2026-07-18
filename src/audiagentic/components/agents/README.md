# Agents Component

Agent profile management — bind a provider to a specific model with optional
execution parameters. Profiles are stored per-project in
`.audiagentic/config/agent-profiles.yaml` and resolved at job launch time.

## Architecture

- `models.py` — AgentProfile dataclass, AgentProfilesStore, validation
- `agents_paths.py` — Path resolution for profile config files
- `agents_api.py` — Pure-logic CRUD API (load, save, list, get, create, update, delete, resolve), agent_status status-hook
- `agents_manage_mcp.py` — Management MCP server (CRUD tools, CLI-side only)
- `agents_mcp.py` — Operational MCP server (resolve tools, provider-facing)
- `agents_gateway_store.py` — Gateway request/result record contract and persisted state (AG08)
- `agents_gateway_queue.py` — Per-profile FIFO queue, concurrency limiting, cancel, wait, lifecycle events (AG09)
- `agents_gateway_dispatch.py` — Provider dispatch, retry, fallback (AG10)
- `agents_gateway_api.py` — Public submit/status/wait/cancel/run API (AG11)
- `agents_gateway_mcp.py` — Gateway MCP server (AG11)
- `agents_gateway_events.py` — Event-triggered submission via `agents.llm.gateway.requested` (AG12)
- `agents_gateway_application.py` — Framework-neutral gateway application contract
- `agents_gateway_service_application.py` — Closed standalone v1 operation/lease router
- `agents_gateway_http_transport.py` — Authenticated IPv4-loopback HTTP adapter
- `agents_gateway_remote_client.py` — Explicit standalone client with bounded attach semantics
- `agents_gateway_service_host.py` — Foundation managed-service host composition

## Two-server pattern (profiles)

Management (`ag-agents-mgmt`, propagate: `audiagentic`) handles admin operations.
Operational (`ag-agents`, propagate: `audiagentic,providers`) provides resolution
capabilities to providers during job execution.

## Error codes

- `VAL-AGP-001` through `VAL-AGP-005` — Profile validation failures
- `RES-AGP-001` — Profile not found
- `RES-AGP-002` — Duplicate profile ID
- `RES-AGP-003` — No default profile
- `IO-AGP-001` — Failed to read profiles file
- `IO-AGP-002` — Failed to write profiles file

## Agent LLM Gateway

A queued, concurrency-limited dispatch layer that resolves an agent profile
to a provider/model and executes provider work through
`providers.services.execution.execute_provider`, with retry and
cross-profile fallback. Deliberately built on its own request/result
contract rather than agent-jobs' `JobRecord` — see [AG07](../../../../docs/planning/completed/agents/AG07.md)
for why (packet/workflow-profile/approvals/review-policy don't fit a
gateway request).

**What `output` actually contains depends on the provider.** For most agent
profiles (any CLI-based provider — claude, codex, aider, etc.), a gateway
request runs a full provider CLI/session invocation and `output` is that
session's stdout, not a raw chat completion — the claude adapter, for
example, wraps the prompt in an execution envelope and injects packet-document
context before invoking the CLI. Only API-style providers (`local-openai`,
any OpenAI-compatible HTTP endpoint) behave like a direct chat completion.
Don't assume `output` is a clean model response unless the resolved profile's
provider is one of the API-style ones.

Persisted at `.audiagentic/runtime/agent-llm-gateway/<request-id>/record.json`,
validated against `agent-llm-record.schema.json`.

### Request modes

- **Async** (default) — `agent_llm_submit` returns `{request-id, state: "queued"}` immediately.
  Poll `agent_llm_status(request_id)` or block later with `agent_llm_wait(request_id, timeout_seconds)`.
- **Blocking** — `agent_llm_run` submits and waits for a terminal result or timeout in one call.
  MCP adapter timeout cap: `agents_gateway_mcp.MCP_BLOCKING_TIMEOUT_SECONDS` (300s) — a longer
  requested timeout is silently clamped, since a blocking MCP tool call must not hold the
  connection past the client's own transport timeout.
- **Event-triggered** — publish `agents.llm.gateway.requested` on the foundation event bus
  (`{project-root, prompt-body, agent-profile-id?, blocking?, source?}`).
  Always async unless `payload.blocking` is explicitly set. Not for one-shot MCP-tool use —
  use `agent_llm_run` for that.

### State model

`queued -> running -> completed | failed | cancelled` (or `queued -> rejected` when the
per-profile queue is full). See `workflows.yaml`'s `gateway-request` kind for the full
transition table. `cancel-requested` is a separate persisted flag, not a state — cancelling
a queued request transitions it straight to `cancelled`; cancelling a running request only
records intent (the dispatch retry loop checks it between attempts and stops, but a
request that finishes normally before the next check completes as `completed`, not `cancelled`
— cancellation of an in-flight provider call is best-effort, not interruptive).

### Params (agent profile `params` block)

All optional, all validated (a present-but-invalid value raises rather than silently
defaulting) — resolved via `agents_gateway_queue.resolve_*` / `agents_gateway_dispatch.resolve_retry_count`:

- `max-concurrency` (int, default 1) — concurrent in-flight requests per profile.
- `queue-max-size` (int, default `max(8, max_concurrency*2)`) — requests rejected once exceeded.
- `retry-count` (int, default 1) — additional attempts after a transient failure, per profile.
- `session-turn-timeout-seconds` (number, default 3600, 0 disables) — hard
  deadline for one session turn (RV680). On expiry the session is failed with
  close-reason `turn-timeout` and the request fails with `TO-AGW-090` — a
  wedged harness can no longer hold a profile compute slot forever.
- `session-turn-silence-timeout-seconds` (number, default 0 = disabled) —
  opt-in in-turn liveness watchdog: if a running turn produces no transport
  events for this long, the reaper fails the session with close-reason
  `turn-stalled`. Only enable for harnesses with a known event cadence.

Cancelling a running SESSION request now also signals protocol-level
`session/cancel` to the in-flight turn (best-effort); an interrupted turn
terminalizes the request as `cancelled` while the session stays usable.
Non-session requests keep the between-attempts cooperative check only.

### Lifecycle events

Published by `agents_gateway_queue` for *every* request regardless of origin (MCP or event):
`agents.llm.queued`, `agents.llm.started`, `agents.llm.completed`, `agents.llm.failed`,
`agents.llm.cancelled`, `agents.llm.rejected`. Base payload: `{request-id, agent-profile-id,
state}`; terminal events (`completed`/`failed`/`cancelled`/`rejected`) additionally carry
`provider-id`, `model-id`, `error`, and `attempt_count` so an observer can tell what happened
without reading `record.json`. `correlation_id`/`subject` are preserved automatically — they
flow from the triggering request's `metadata` through to every lifecycle event for that request.
Publish never raises even if the event bus or a subscriber misbehaves — a broken observer
must never prevent a request from reaching its real terminal state.

### Restart reconciliation

`GatewayQueueManager` is an in-process singleton. A restarted host cannot recover
the old worker's execution state, so `agents_gateway_api.reconcile_gateway_state(project_root)`
performs one-shot cleanup for persisted non-terminal records: `running` requests become
`failed` with an orphaned-after-restart error, and `queued` requests become `rejected`.
The reconciliation is idempotent and leaves already-terminal records untouched.

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
  or running work after service-process failure is owned by SH07; the existing
  one-shot reconciliation remains the current orphan classifier until then.
- **Automatic mode is not yet the default**: SH11 owns consumer cutover and
  removal of in-process ownership. SH04 standalone and SH05 automatic modes
  remain explicit migration choices.
