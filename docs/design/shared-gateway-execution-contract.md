# Shared gateway execution and joined-session contract

Status: base design approved by terminal source-level GPT compliance review at
`b760024580c53f03fc5cb0c7c3aa92aff6047e73`; final review records are RV1213 and
RV1214. The clarified A2A addition awaits a focused final audit. SH35/SH36 own
planning; SH37-SH43 remain pending delivery/qualification.
No runtime capability is enabled here. Prior release prerequisite: v0.6.0.

## Scope and decisions

Support a shared standalone gateway, server-hosted execution, caller-local
execution nodes and qualified registration of existing human-owned Claude Code,
Codex, Pi and OpenCode sessions. Only integrations already present and qualified
in the actual running session are eligible. Missing integrations are later work.

Use one canonical gateway session ID, an independently supervised node and one
remote control writer per native instance/session/generation. Queue is default.
Steer is separately gated; reject it until independent result attribution is
qualified. No per-request override or acknowledgement-only successful answer.
External ownership always means detach, never process termination.

Do not add terminal typing, substitute ACP children, ownership transfer,
cross-node failover, repository mirroring, another scheduler/session registry or
MCP-scoped node lifetime. Inventory may show unsupported candidates; failed
admission must not create a canonical joined session or binding.

## Source seams and ownership

| Owner | Existing source | Required change |
|---|---|---|
| Agents | `gateway/api.py`, `application.py`, `queue/` | Sole request/session admission, grants, FIFO and explicit joined-target dispatch |
| Agents | `gateway/session/{bindings,sessions,controls}.py` | Immutable binding generations, writer fencing, external detach, pre-send durability |
| Agents | `gateway/remote_client.py`, `gateway/client.py`, `service/` | Extend existing client/host/lifecycle and scopes; no second server |
| Providers | `providers_api.py` | Approved cross-component API for static and live surface qualification/dispatch |
| Providers | `descriptors/session_surface_declarations.py`, `loader.py`, `services/session/session_surface_resolution.py`, `harness_observability_inventory.py` | One typed declaration/evidence/resolution authority |
| Providers | Native adapters and `config/providers/*.yaml` | Native identity/control/observation/detach, requester-blind |
| Foundation | `transports/{session_surface,session_binding,agent_session}.py`, `system/managed_service*` | Neutral values, lifetime/service primitives only |
| Composition roots | Launcher, server and node startup | Distinct process graphs, factories and lifetimes |
| CLI/MCP/service adapters | `commands/gateway.py`, owning MCP/HTTP handlers | Translation only; no stores, queues, lifecycle or provider internals |

Verified current baseline: protocol is `gateway-service-v3`, host/HTTP server and
client endpoint validation are loopback-only; `_call()` carries a local project
root. Dashboard reads rely on loopback assumptions. Current gateway startup loads
too much interactive application state. None constitutes remote authority.

## CLI and configuration

Proposed canonical keyword grammar, not shipped commands:

```text
audiagentic gateway help
audiagentic gateway serve help
audiagentic gateway serve config FILE
audiagentic gateway connect config FILE project PATH dry-run
audiagentic gateway connect config FILE project PATH non-interactive
audiagentic gateway status config FILE output json
audiagentic gateway drain config FILE
audiagentic gateway resume config FILE
audiagentic gateway stop config FILE
audiagentic gateway recover config FILE
audiagentic gateway node help
audiagentic gateway node serve config FILE
audiagentic gateway node status config FILE output json
```

Serve runs foreground under OS supervision. Connect validates/writes the existing
owning standalone implementation binding through its approved writer; dry-run is
read-only. Recover is local owner-record recovery, never remote PID kill. Remote
lifecycle actions require an operator grant. No active-connection registry,
start alias or automatic local fallback. Every action/domain has pure help with
words/defaults/examples/output/errors, without browser/provider/app startup.

Agents owns versioned server/connector/node schemas. Server owns durable state,
loopback backend, front-door trust, principal grants, project roots, resource and
retention policy. Connector owns endpoint, credential-file reference, server and
project/topology identity. Node owns enrolled identity/credential reference,
workspace-to-local-root map and allowed installed surfaces. Credentials are never
inline. Explicit config wins over selected owner options; an environment override
must provide a complete validated connection tuple, never a mixed endpoint/token.
No cwd-based remote discovery. One component profile per worker/process.

New shared ingress uses a versioned handshake and rejects incompatible peers.
Do not weaken local endpoint guards or fall back to embedded execution. Existing
local implementation remains intentional, not a compatibility shim. Architecture
does not authorize retaining legacy argv aliases by default: migrate callers,
docs/tests and remove obsolete gateway paths in the delivery change. A proven
external obligation requires an explicit bounded exception before implementation.

## Network and deployment

Use HTTPS front door and loopback backend; node uses an outbound authenticated
WSS command/evidence connection. Application validates principal, audience,
issuer, expiry and scope for every operation, including reads. Do not forward
legacy dashboard/images/routes publicly. Minimal unauthenticated liveness reveals
no operational state; readiness/diagnostics require authorization. Enforce
credential rotation/revocation, frame/request bounds, quotas, origin policy and
trusted proxy header overwriting; prevent direct backend access. A shared static
operator token is not per-client authorization.

Initially install the existing application wheel plus validated dependencies and
component set. MP02 owns actual slim distributions. Document systemd and Windows
foreground supervision, secret/state permissions, backup/drain/upgrade/rollback,
startup/readiness and browser login/CDP placement. Shared lifetime does not end
with zero client leases. Browser integration remains Provider-owned on execution
side; Windows session-0 limitations and health-versus-login must be explicit.

## Execution identity and grants

| Execution mode | Root authority | Central storage authority |
|---|---|---|
| Server-hosted | Operator project ID maps to server checkout | Principal/project/profile scope |
| Node-local | Enrolled node maps authorized workspace ID to actual root | Principal/node/workspace scope, not a fabricated checkout |

Never canonicalize a foreign OS path centrally. Node resolves local execution
facts and attests workspace/provider/model/profile fingerprint; gateway freezes
authorized topology and that fingerprint. Path strings alone are not manifests.
Migrate path-based session-store callers through one scope resolver. Client-local
paths remain protected local provenance, not public diagnostics or authority.

Administrative node enrollment/workspace grants precede registration. Principal
authentication precedes lookup; session ID knowledge is not permission. Grants
separate observe, submit, cancel-own-request, detach and operator actions.
Revocation denies new admission immediately; already accepted work is observed
with restricted output, not silently interrupted. Receipts survive detach.

Canonical session -> immutable binding/generation -> node/workspace + surface,
version, evidence digest, external ownership and opaque node locator. Central
binding does not store raw native ref/PID/credential endpoint. Node privately maps
the scoped, revocable locator to exact native identity/process birth evidence.
Locator is not authorization. Context groups work; each remote prompt has its own
request/Work ID. Same proven instance can reconnect; a replacement gets a new
session by default, optionally Context-linked. Never retarget latest session.

## Capability-based admission

Reuse declaration -> typed loader -> `ResolvedSessionSurface` -> Provider public
resolution, followed by passive node-local current-instance attestation. Generate
matrix/status/help from this authority, not a parallel provider-name allowlist.
Distinguish upstream API, implemented adapter, qualified version/platform and
current-instance readiness.

Confirmed gaps: installed version may fall back to a declaration constraint;
`_get_inventory_proof()` permits absent inventory; adapter factory existence is
not attachment evidence. Strict joined qualification requires positive proof,
actual node-local version/platform and a callable qualified adapter. Preserve
ordinary owned ACP semantics; observation-only validation cannot authorize joins.

Extend existing declaration/resolved types with one narrow typed joined group
only where needed. Reuse identity/EXTERNAL/mapping/control/lifecycle/content and
platform fields. Mandatory conjunction: passive exact current identity, safe
external detach, prompt delivery, native queue admission against human input,
correlated terminal output and safe shared-human concurrency. Queue-only may
qualify; steer/interrupt are independently gated.

Proposed Provider API operations (contract sketch, not shipped signatures):

```python
ready = providers_api.inspect_joined_session(local_root, trusted_context)
# Existing resolver + strict evidence + passive exact-instance proof.
# Agents authorizes and atomically commits canonical registration/writer claim.
receipt = providers_api.dispatch_joined_session(command, expected_generation,
                                                expected_evidence_digest)
# Same adapter; live identity/admission recheck immediately before effect.
```

On unsupported/unproven/unavailable outcome, return a compact actionable reason
without creating a session/binding. No auto-install/restart/hidden smoke prompt or
arbitrary model-supplied PID/ref proof. A previously valid binding losing evidence
becomes unroutable, retaining identity; full revalidation precedes restoration.
Authorization, capability, writer epoch and generation gates apply before sends.

## ACP, native interfaces and qualification

ACP is Agent Client Protocol. Reuse existing neutral ACP transport/Provider launch
contracts for qualified owned execution and persisted resume. ACP support never
implies attaching to a human TUI or steering. A qualified native existing-session
adapter implements the same neutral contract; gateway does not know native RPCs.

The user confirmed ASA meant A2A. Use the two standards at different boundaries:

| Boundary | Protocol and owning implementation | Identity/lifecycle |
|---|---|---|
| Harness calls gateway tools | Existing stdio MCP, thin Agents adapter | Canonical Context/Work/session, same grants |
| External agent calls published gateway agent | A2A projection in `components/agents/protocols/a2a/` | A2A context -> Agent Context, task -> Work |
| Gateway controls a qualified ACP agent | Existing neutral foundation ACP transport + Provider launch/control | Provider-owned native session bound to gateway session |
| Gateway controls existing human session without usable ACP attach | Qualified Provider native surface | Same neutral binding/delivery/ownership contracts |
| Node exchanges commands/evidence with gateway | Internal authenticated versioned channel | Node epoch/generation/command receipts, not another A2A task engine |

A2A is an external agent interoperability projection, not a requirement that all
four harnesses expose a native A2A server. ACP likewise does not make their human
TUIs attachable. Prefer an already-qualified native standard surface; do not wrap
every native API in a second ACP process or use A2A to bypass join admission.
Sources: [A2A specification](https://a2a-protocol.org/latest/specification/) and
[ACP v1 overview](https://agentclientprotocol.com/protocol/v1/overview). Pin actual
implemented/negotiated versions and capabilities; ACP v2 is draft, not an implied
migration requirement. The existing A2A module's 1.0 label and ACP adapter's SDK
version label are not end-to-end conformance or deployment evidence.

### A2A and external ACP implementation contract

Reuse `protocols/a2a/{server,agent_card,mapping}.py`,
`protocols/acp/{agent,server,mapping}.py`, and injected `GatewayClient`/application
ports. AS65/AS66 are superseded historical plans, not current qualification.
Do not add an A2A task store, session registry, native adapter lookup or unaudited
outbound endpoint discovery. Publish only explicitly configured Agent Definitions
and granted targets. Agent Cards expose only implemented capabilities; streaming,
push notifications, rich content and steer stay unsupported unless separately
qualified. Do not advertise live native session IDs/locators in public cards.

Add an explicit owner-validated optional joined execution target to canonical
Context creation/binding, using the existing gateway session ID, immutable
generation and evidence digest. The authorized management/join path resolves it
before an A2A or external ACP call; subsequent standard context/session IDs route
through that frozen Context. No untyped metadata/native ID routing parameter or
adapter-owned target registry. Replacement target requires a new validated
Context/binding, never silent retarget. Expose the authorized Context correlation
alongside the joined session through existing status/management projections.

`gateway/application.py:submit_agent_work()` must propagate that authorized
target through explicit canonical admission fields, not its current owned/new
execution default or reserved `idempotency_key` metadata. A2A and external ACP
read/cancel/output use the same Work owner and external no-kill controls. A2A
task IDs are Work IDs, not native turn IDs or gateway session IDs. Server-hosted
and node-local scopes use SH37/SH38 authority, not untrusted protocol cwd paths.

Source hazards assigned to SH43: both current external adapters derive message
identity from text, incorrectly collapsing two intentional identical prompts;
A2A `taskId` branch returns prior Work rather than validating new-message
continuation; ACP `prompt()` reads output immediately and returns end_turn
without a proved terminal Work; initialization echoes requested version. Require
protocol-envelope message/delivery identity and canonical owner idempotency:
same key/same content is replay, same key/different content conflicts, distinct
messages with identical text remain distinct. If a peer protocol has no stable
replay key, allocate a distinct command identity and preserve uncertainty rather
than deduplicating content. End a turn only on correlated terminal evidence.

Validate principal/project/Agent Definition/Context/Work/session ownership before
every operation, including existing-context sends, task reads/cancel and card
discovery. Normalize public errors through registered owner errors and protocol
mapping. Thin adapters never read native transports/stores or poll ad hoc. Inject
an owner wait/event subscription for asynchronous Work; closure/cancellation is
capability-scoped, never broad cancellation of other clients' work. Add negotiated
version mismatch, duplicate/distinct text, concurrent clients, cross-agent and
cross-principal denial, restart, late completion, repeated multi-turn context and
owned-versus-joined tests. Real external clients and wire schemas must validate
conformance; fake port tests prove only the semantic seam.

| Harness | Research lead | AUDiaGentic joined status |
|---|---|---|
| Claude Code | Existing opted-in Channels; exact delivery/output attribution | Unproven; reject |
| Codex | Exact existing App Server/thread plus human UI | Unproven; reject |
| Pi | Existing in-process extension; RPC child is different | Unproven; reject |
| OpenCode | Actual existing TUI server/session and SDK | Unproven; reject |

This is research status, not runtime declarations. Previous version-only inventory
was Claude 2.1.288, Codex 0.153.4, Pi 0.84.1, OpenCode 1.18.25; re-inventory before
probes. Primary research leads, not installed-version proof:
[Claude Channels](https://code.claude.com/docs/en/channels-reference),
[Codex App Server](https://developers.openai.com/codex/app-server),
[Pi extensions](https://pi.dev/docs/latest/extensions),
[Pi RPC](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md),
[OpenCode server](https://dev.opencode.ai/docs/server/).

## Node lifetime and external cleanup

Node command I/O remains independent of blocking MCP waits with bounded queues,
backpressure, sequence checkpoints and node boot epochs. Gateway is scheduling
authority; node owns native side effects and durable receipt evidence only.
Reuse managed-service lifecycle, not another gateway. Duplicate MCP children
cannot become competing control writers or steal native stdio ownership.

| Event | Required EXTERNAL behavior |
|---|---|
| Close/unregister/dashboard detach | Revoke route/subscriptions, detach only |
| Idle/reaper/purge/failed attach/shutdown | Same no-kill rule, including parent/shared daemon |
| Own queued cancel | Atomically remove undelivered request only |
| Gateway restart | Reconcile exact binding/receipts, never resubmit blindly |
| Node restart | New epoch, exact continuity proof before restoration |
| Native exit/replacement/PID reuse | Refuse old binding; no latest-session guess |

Audit `AgentSessionTransport.close()` and SessionRuntime close/close-all/client
cleanup paths. Add neutral detach operation if required. No proven detach means
registration rejection, never fallback to close/kill. OWNED semantics remain;
ADOPTED is outside scope. MCP connector exit does not kill node/native process.

## Delivery and concurrency state contract

Gateway FIFO orders remote requests, not human prompts. Native conditional
admission/serialization must close the busy-snapshot/send race. Unknown native
ordering or acceptance correlation means unproven. Native approvals remain human
owned; joining never grants approval bypass.

| Fact | Persistence/recovery rule |
|---|---|
| admitted/queued | Canonical request/principal/FIFO; atomic own cancel |
| dispatch-intent | Command/request/generation/attempt and payload digest/reference durable before effect |
| sent-uncertain | Reconcile exact evidence; never blind replay |
| native-accepted | Stable native receipt, not completion |
| native-started | Correlated work evidence, distinct from heartbeat |
| native-settled | Exact terminal evidence; still verify result ownership |
| verified-response | Request-specific output proof, then complete |
| needs-reconciliation | Fence generation, release compute reservation honestly; retain unresolved receipt |

These facts map onto existing lifecycle, not a second scheduler/state authority.
Do not copy `controls.execute_once()` dispatch-before-save ordering. Node WAL is
transactional delivery evidence, not another session store. Without native
idempotency/queryable turn evidence there is no exactly-once guarantee. Definitive
exact-command evidence can resolve automatically after renewed authorization;
otherwise bounded reconciliation ends delivery-uncertain and needs operator
clearance. Time elapsed never authorizes replay or clears a generation fence.

Cancellation after native acceptance records intent separately from physical
execution. One caller cannot automatically interrupt a human/shared turn. Steers
need separate contribution receipts; a shared completion cannot settle unrelated
requests. Trusted caller session/generation/turn and causal parent detect submit
and wait cycles, including async self-submit followed by polling. Source labels
from model arguments are not identity proof.

Configured observation/reconciliation deadlines are separate from native work
progress, queue wait and client keepalive. At most one bounded retry of an
idempotent transient boundary operation; no auth/config/contract retry or prompt
resend loop. Synthetic heartbeat never masks unsent/stalled work. Reconnect is
bounded supervised lifecycle, not retry of the native side effect.

## Data, observability and tools

No raw prompt/output/secret in logs, timeline, generic durable metadata or node
receipts. Content artifacts use only existing explicitly protected owner
contracts, permissions and retention; resolve any standards exception before
implementation. Central node-local records keep digest/reference, not duplicate
native transcripts. Credentials stay execution-side. Artifact transfer is
explicit bounded authenticated size/hash/expiry-checked access; never return an
unusable local path as remote output or implicitly upload a worktree.

Use shared `record_timeline_event` and appropriate redacted operational records;
no local JSONL writers. Include owner/resource/correlation, admission-to-send/ack/
start/settle timings, queue delay, evidence digest, epoch and safe failure reason.
Node WAL is primary state, not a best-effort timeline. Retention preserves active
and uncertain evidence through existing owner policies. Declare bus topics and
public error codes in owning config before use.

Reuse submit/status/response/cancel/close tools. One join-current-session tool is
justified through trusted local integration context, not arbitrary IDs. Existing
list/status should expose compact derived eligibility/ownership/reason instead
of another capability tool. Active-only session default and explicit history
remain; do not duplicate structured payloads as verbose text.

Update owner Agents config/implementation schema/errors/events; Provider schema,
descriptor evidence/adapters; command help; exact tool/parameter descriptions;
short owned instruction contributions; installed assets; deployment/joining/
migration/trace guides and dashboard external/detach labels. Regenerate managed
instructions, never hand-edit AGENTS or copy catalog fragments.

## Standards-to-evidence gates

| Standard | Obligation | Delivery proof |
|---|---|---|
| Architecture 1/6/8 | Approved Provider public API, thin adapters, process composition | Import/boundary tests and source audit |
| Architecture 2/3 | Typed declarations, one owner, evidence-led scope | Schema/loader tests; no new central name switch/registry |
| Architecture 4 | No default compatibility paths, owning errors, safe content | Caller migration searches; error registry/redaction tests |
| Architecture 5 / guideline events | Declared topics, isolated async failure | Event contract and safe durable failure tests |
| Architecture 7 | Scope-matched validation | Focused, installed, multi-machine and native results reported separately |
| Guidelines MCP/schema | Config-owned exact metadata | Real tools/list/call, import/schema/parameter parity |
| Guidelines external failures | Bounded idempotent retry | Crash/ack-loss matrix; auth/config refusal; no duplicate send |
| Observability standards | Correlated durable milestones | Inspect real admission/queue/send/settlement/failure traces |
| Project doctrine | First nonempty prompt tag, provenance | Provider/surface/session correlation without content leakage |
| Profile/ownership doctrine | One component profile/process, no-kill EXTERNAL | No global profile mutation; kill-sensitive lifecycle sentinel tests |
| Planning/ledger | Findings before corrections, distinct design/runtime claims | Closed incorporated reviews, linked ledger, exact-head terminal GPT audit |

Baseline suites: planning integrity; Provider surface resolution/declaration/API;
foundation surface/binding; launcher arguments; component MCP metadata/imports;
architecture boundaries. Add behavioral tests in delivery slices, not doc mirrors.

Required scenarios: two clients plus human, duplicate join, conflicting grants,
same repo name on two nodes, mixed OS roots, blocked MCP/self-route, stale epoch/
PID, native busy race, crash at every WAL boundary, output misattribution, node/
connector/native exit, browser disconnect, gateway restart, revocation, queued/
accepted cancellation, detach/reaper/purge, profile drift and artifact transfer.
Prove external process/parent/daemon survival with kill-sensitive sentinels.
Disposable native probes pin platform/binary/schema/adapter/evidence digest;
simulation is never attachment qualification.

## Completion boundary

Design completion requires exact-head terminal GPT standards/code-seam review,
closed findings, acceptance mapping and bounded pending delivery items. Runtime
completion separately requires implementation review and real qualification for
each advertised surface. A release with zero qualified joins is infrastructure
only, not working joined-session functionality. Missing integrations, adoption,
MCP-scoped nodes, per-request steering, acknowledgement-only steer, cross-node
failover, other providers, MP02 slim packages and SH25/SH28 broker changes remain
outside this delivery scope.
