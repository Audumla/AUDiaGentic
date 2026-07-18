# Agent execution transports

Evidence checked 2026-07-13. Transport facts describe how a provider can be
driven; they do not define provider identity, model catalogs, or orchestration.

| Provider | Version | Transport | State | Manifestation | Evidence |
|---|---:|---|---|---|---|
| OpenCode | 1.17.18 | ACP protocol 1 over stdio | supported | `opencode acp --cwd <root>`; runtime model override through `OPENCODE_CONFIG_CONTENT` | installed `--version`/`acp --help`; official ACP registry entry |
| OpenCode | 1.17.18 | CLI stream | supported | `opencode run --format json --model <id> <prompt>` | real gateway round-trip |
| Pi | current install | ACP through `pi-acp` adapter | unverified | external adapter, not native Pi capability | official ACP registry distinguishes adapter package |

## Ownership

- `foundation.execution`: generic ACP framing/lifecycle, ordered neutral events,
  default-deny permissions. No provider IDs, profiles, retries, queues, or stores.
- provider adapter: executable, arguments, runtime config/auth differences.
- agents gateway: profile/model selection, retry/fallback, queue, persistence, and
  projection of transport-neutral events.
- MCP/CLI/SSE consumers: projections of same event sequence. MCP remains control
  surface; ACP remains optional provider execution transport.

## Keep / map / delete

| Existing concern | Decision |
|---|---|
| Agent profiles, gateway queue, retry/fallback, request records | Keep |
| CLI/HTTP provider extractors | Keep as fallback transports |
| ACP session updates | Map to ordered `AcpEvent`; retain source payload |
| Permission requests | Map to event; deny unless explicit policy port exists |
| `components/providers/protocols/acp` inter-agent scaffold | Delete; wrong protocol name and ownership |
| New ACP queue, session store, event store, string registry | Do not create |

## Current proof and integration boundary

Real OpenCode/deep-coder ACP session produced incremental thought and assistant
message chunks plus usage update through official Python SDK 0.11.0. Shared
transport and the thin OpenCode launch binding are validated. The focused
foundation/provider suite proves cancellation, bounded rolling retention,
terminal-result preservation, callback isolation, default-deny permissions,
redaction, malformed updates, child exits, and launch isolation. The documented
clean-wheel Docker gate proves the packaged `[acp]` extra and foundation import
boundary on Linux.

MA18 transport validation is complete. Provider execution composition and
gateway event projection belong to MA17 and later session/gateway items; they
must reuse this neutral transport rather than extending it with provider,
profile, queue, retry, or persistence concerns. Real-provider E2E remains an
optional environment check and is not part of the clean packaging contract.

Sources:

- https://github.com/agentclientprotocol/agent-client-protocol
- https://github.com/agentclientprotocol/python-sdk
- https://agentclientprotocol.github.io/python-sdk/quickstart/
- https://github.com/agentclientprotocol/registry/blob/main/opencode/agent.json
- https://opencode.ai/docs/config/
- https://opencode.ai/docs/models/

## Neutral event and lifecycle contract — FROZEN (MA18 Steps 2–3, T3 decision 2026-07-14)

This section is the implementation contract for MA18 Step 2 (foundation
hardening) and the canonical event input to MA16 execution declarations.
T2 agents implement exactly this; deviations require a plan review on MA18.

### Canonical event fields (all transports)

Every transport-neutral event carries:

| Field | Type | Semantics |
|---|---|---|
| `sequence` | int | 0-based, strictly increasing per run; assigned at normalization, never by the transport |
| `kind` | str | canonical vocabulary below; raw transport kind goes in `ext` |
| `timestamp` | str | ISO 8601 UTC, assigned at normalization |
| `session-id` | str | transport session identifier, opaque |
| `text` | str or null | safe display text extracted from the update; bounded per limits below |
| `terminal` | bool | true on exactly ONE event per run — the last |
| `error` | null or {code, message} | canonical registered code; message never contains raw payload/secret bytes |
| `ext` | dict | namespaced by transport (`ext.acp = {raw-kind, payload}`); lossless in memory, REDACTED before any durable consumer |

Canonical `kind` vocabulary (closed set; new kinds require MA18 review):
`assistant-message`, `thought`, `status`, `usage`, `tool-call`,
`file-change`, `terminal-output`, `plan-update`, `permission-request`,
`error`, `result`. `result` is the sole terminal kind; `stop_reason`
(`completed|cancelled|error|<transport value>`) rides in its payload.

### Lifecycle semantics

- **Cancellation**: `run_acp_prompt` accepts an optional cancel signal
  (`asyncio.Event`). On cancel: attempt protocol-level session cancel, then
  bounded child termination (terminate, 5s grace, kill). Exactly one terminal
  `result` event with stop_reason `cancelled` regardless of races. Cancel
  before prompt start yields an empty run with the same terminal shape.
  Cancellation is an outcome, not an error — no error code.
- **Malformed update**: normalize to non-terminal `error`-kind event with
  code `EXT-ACP-002`; message is generic; offending bytes bounded in `ext`
  only. Session continues if the connection survives; otherwise fall through
  to child-exit handling. Never raise through the event loop.
- **Unexpected child exit**: terminal `result` with `error` code
  `EXT-ACP-003`, returncode in payload; stderr excerpt bounded in `ext`,
  never in `message`.
- **Callback failure**: `on_event` exceptions are isolated and counted; after
  3 consecutive failures the callback is disabled for the rest of the run
  (recorded as a `status` event). Event collection and the terminal result
  are never lost to a callback failure.
- **Bounded delivery** (defaults, overridable per call): max 10 000 events
  per run; max 64 KiB payload per event (truncate, mark `truncated: true` in
  `ext`); max 8 MiB total buffered event bytes (beyond it, non-terminal
  payloads are dropped to header-only but sequence/kind/text-summary are
  kept). The terminal event is always retained in full (post-truncation
  rules still apply to its `ext`).
- **Permissions**: default deny stays (`cancelled` outcome). An explicit
  optional policy callback parameter is the only grant path; transport never
  grants silently.
- **Redaction boundary**: in-memory `AcpResult` may hold lossless payloads;
  every durable consumer (gateway timeline, logs, MCP cursor) receives events
  only after redaction of `text`, `error.message`, and `ext`.

Registered error codes: `CFG-ACP-001` (dependency missing, exists),
`EXT-ACP-001` (execution failed, exists), `EXT-ACP-002` (malformed update,
new), `EXT-ACP-003` (agent process exited unexpectedly, new),
`CON-ACP-001` (session transport not open, sessions extension below).

### Session lifecycle extension (RV512 on MA18; plan agent-sessions AS01)

`AcpSessionTransport` keeps one child process and one protocol session alive
across multiple `prompt()` turns: `open()` (spawn → initialize →
new_session), `prompt()` × N, `close()` (idempotent; SDK unwind bounded by
the 5s grace, then force terminate/kill — the child is never leaked, even
when `open()` itself fails). The frozen per-turn event semantics above are
UNCHANGED — every `prompt()` turn gets its own bounded-delivery pipeline and
exactly one terminal `result` event. Process lifetime == session lifetime:
no resume-after-death at this layer (AS10 build-out). Session updates
arriving between turns are dropped and counted (`dropped_between_turns`).
A child death mid-turn marks the transport dead; later `prompt()` calls
raise `CON-ACP-001`. `run_acp_prompt` remains the behaviour-identical
one-shot wrapper (open → prompt → close).

### Opens for dispatch

With this contract frozen: MA18 Step 2 (implement above in
`foundation/execution/acp.py`, T2), Step 4 (test matrix pinned by this
table, T2), Step 5 (OpenCode binding tests, T2), Step 6 (Docker `[acp]`
wheel smoke, T2), Step 7 (evidence update, T1) may proceed without further
T3 input. Steps 8–9 remain gated on MA16/MA17.
