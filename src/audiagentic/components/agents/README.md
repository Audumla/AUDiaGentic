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
  Server-side timeout cap: `agents_gateway_api.MAX_BLOCKING_TIMEOUT_SECONDS` (300s) — a longer
  requested timeout is silently clamped, since a blocking MCP tool call must not hold the
  connection past the client's own transport timeout.
- **Event-triggered** — publish `agents.llm.gateway.requested` on the foundation event bus
  (`{project-root, prompt-body, agent-profile-id?, fallback-profile-ids?, blocking?, source?}`).
  Always async unless `payload.blocking` is explicitly set. Not for one-shot MCP-tool use —
  use `agent_llm_run` for that.

### State model

`queued -> running -> completed | failed | cancelled` (or `queued -> rejected` when the
per-profile queue is full). See `workflows.yaml`'s `gateway-request` kind for the full
transition table. `cancel-requested` is a separate persisted flag, not a state — cancelling
a queued request transitions it straight to `cancelled`; cancelling a running request only
records intent (the dispatch retry/fallback loop checks it between attempts and stops, but a
request that finishes normally before the next check completes as `completed`, not `cancelled`
— cancellation of an in-flight provider call is best-effort, not interruptive).

### Params (agent profile `params` block)

All optional, all validated (a present-but-invalid value raises rather than silently
defaulting) — resolved via `agents_gateway_queue.resolve_*` / `agents_gateway_dispatch.resolve_retry_count`:

- `max-concurrency` (int, default 1) — concurrent in-flight requests per profile.
- `queue-max-size` (int, default `max(8, max_concurrency*2)`) — requests rejected once exceeded.
- `retry-count` (int, default 1) — additional attempts after a transient failure, per profile.
- `fallback-profile-ids` (list[str], default `[]`) — tried in order after retries on the
  current profile are exhausted, but only for *transient* failures (network/timeout/external/
  internal/IO errors). A validation/config failure (unknown profile, disabled provider,
  invalid request, missing model) is terminal on the first occurrence — never retried, never
  falls back. Classification is driven by the error's canonical code prefix
  (`foundation.contracts.errors.ERROR_CODE_PREFIXES`), not per-provider special-casing.

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

### Known limitations

- **No cross-process durability**: `GatewayQueueManager` is an in-process singleton. If the
  hosting process restarts, persisted `queued`/`running` records are orphaned — no worker
  resumes them. Tracked as a follow-up: [AG14](../../../../docs/planning/active/agents/AG14.md).
- **Not project-scoped**: the queue manager singleton is process-wide, not keyed by
  project-root. Fine in practice (one project per process), but worth knowing.
