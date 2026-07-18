# Gateway shared-service architecture — v2 (SH01 program boundary)

Status: **frozen v2 — sponsor approved 2026-07-17** (SH01 closed)
Supersedes: the v1 (EDJ13) "defer until approved" decision of 2026-07-12. The
multi-instance requirement is now approved; every deferred v1 row is re-opened
below and assigned an owning migration item. The v1 decision record is
retained as Appendix A for provenance.

Scope: design authority only. This document freezes the target topology,
layer map, ownership boundaries, phase gates, compatibility/security policy,
and non-goals for the shared-gateway program (SH02–SH11). It adds no
implementation.

Implementation status (2026-07-18): SH04 supplies the explicit, opt-in
standalone service described here. It uses authenticated IPv4-loopback HTTP
and the foundation managed-service lifecycle. Automatic discovery/default
cutover remains SH05/SH11, and durable in-flight recovery remains SH07.

## 1. Requirement

Many harness sessions and projects on one machine share a single gateway
control plane, so that:

- work survives the submitting client's exit (no daemon-thread loss),
- sessions can be observed/continued from other authorized clients (AS08/AS09),
- two projects with different roots, component profiles, MCP sets, provider
  configs, and credentials execute concurrently without state bleed (SH06),
- queue/resource policy is machine-wide, not per-process (SH08).

## 2. Target topology

```text
thin inbound adapters                 control plane (one authority)          execution
──────────────────────                ─────────────────────────────          ─────────
MCP facade (agents_gateway_mcp) ─┐
CLI adapter                      ├─→ gateway client API ─→ shared gateway ─→ context-isolated
event ingress (SH09)             │   (framework-neutral)   service:          workers / provider
local service transport (SH04) ──┘                         store, queue,     processes (SH06),
                                                           session registry, launched via
                                                           dispatch policy   providers_api
                                                                             execution (MA17)
                                                                             + ManagedProcess
                                                                             (PR05/PR07)
```

Principles:

1. **One authority, not one process.** The control plane is the single owner
   of request/session state and dispatch decisions; execution happens in
   context-isolated worker processes because component profiles are
   one-per-process and several providers have fixed/partial config isolation
   (SH06, MA20 isolation-tier facts).
2. **Machine-wide control plane, project-scoped work.** Discovery identifies
   a control plane, never a project (SH05). Project identity, root, and
   profile selections travel in every SH02 execution envelope and resolve to
   an immutable execution manifest with a canonical context fingerprint.
   Provider configuration owns environment shaping and secret materialization;
   neither travels in the envelope. SH06 worker-reuse keys and SH07
   idempotency identity derive from that one fingerprint (RV561).
3. **Inbound adapters are thin (AR25).** MCP/event/CLI/service transports
   translate protocol context and transport-only constraints (e.g.
   `MCP_BLOCKING_TIMEOUT_SECONDS` belongs to the MCP transport, not the API —
   SH03 step 4), call the public API, and serialize results. They own no
   store, queue, dispatch, discovery, worker, or lifecycle policy.
4. **Job state has one durable owner.** SH07's durable request record is the
   job-state authority; the AS21 lifecycle projection is its
   transport-independent evidence input, with fidelity determined by AS19
   capability declarations — never by transport-name branching (RV561). An
   O0 harness still yields correct durable state; ACP/App Server only raise
   fidelity.

### 2.1 State home (decided 2026-07-17)

Ownership of durable state is split by who the state belongs to:

- **Project-owned records stay in the project tree.** Request/session records,
  timelines, and results for a project's jobs remain under
  `<project>/.audiagentic/runtime/agent-llm-gateway/`, written by the control
  plane through the resolved manifest's project root. A project can always see
  exactly what is its own with plain files in its own tree; nothing
  project-meaningful lives only in the user home.
- **Control-plane core state lives in a machine-scoped home** (user-local,
  e.g. `~/.audiagentic/gateway/`): service identity/discovery/lease records
  (PR06/PR07), the service journal/log, machine-wide admission accounting,
  and a **rebuildable active-work index** — references only (project root,
  request id, epoch), never record content or secrets.
- **Recovery order:** on restart the service reads the index to find claimed
  in-flight work, then visits each project store, where the records are the
  source of truth. A dangling index entry (project moved, drive absent)
  produces an explicit degraded/orphan outcome, never silent loss; the index
  can always be rebuilt by rescanning known project roots, so corruption of
  the home directory is not fatal to project state.

## 3. Layer map and automated dependency checks

| Layer | Modules (current → target) | May import |
| --- | --- | --- |
| Inbound adapters | agents_gateway_mcp, CLI wiring, SH09 event ingress, SH04 service transport | public gateway client API + protocol scaffolding only |
| Public API | gateway client / application / control-plane contracts (SH03) | SH02 contracts; no MCP/FastMCP, no broker, no transport framework |
| Domain | store, queue, session registry, dispatch, admission (behind control plane) | foundation primitives, providers_api public exports |
| Outbound seams | providers_api execution entry (MA17), ManagedService/ManagedProcess (PR05–PR07), EventBus/FileEventStore | — |

Automated checks (extend the existing suites; SH03/SH11 own delivery):

1. Core/API/service modules import no MCP/FastMCP or selected local/broker
   transport framework (SH03, SH04, SH09, SH11 validations).
2. Adapters reach gateway behavior only through approved public APIs; no
   store/queue/dispatch/discovery/worker/lifecycle policy in adapter modules.
3. agent-jobs events-only boundary test (`tests/unit/jobs/test_gateway_boundary.py`)
   is retained unchanged.
4. No lock/PID/discovery-record/process-launch/lease/retry policy in MCP/CLI
   adapters (SH05 validation).
5. Foundation imports no component module (existing guard).

## 4. Same-process assumption inventory → owning migration items

v1 rows re-opened plus session-era additions. Every row has exactly one
owning item; SH11 deletes the residue.

| # | Assumption (location) | Failure mode when shared | Owning item |
| --- | --- | --- | --- |
| 1 | `_QUEUE_MANAGER` module singleton (agents_gateway_api.py:40) owns queues/workers per process | double-dispatch over one store; in-memory depths diverge from disk | SH03 (seam), SH04 (service ownership), SH11 (deletion) |
| 2 | `wait_llm_request` wakes only same-process waiters | wait in A for work dispatched by B never wakes | SH04 |
| 3 | `cancel_llm_request` reaches only same-process workers | cancel in A cannot interrupt B's worker | SH04 + SH07 (requested/acknowledged/terminal semantics) |
| 4 | `MCP_BLOCKING_TIMEOUT_SECONDS` + compat alias live in agents_gateway_api.py | transport constraint frozen into the API contract | SH03 step 4 (move to MCP boundary) |
| 5 | Store per-request `threading.Lock` registry (agents_gateway_store.py:44) — single-writer assumption | cross-process lost updates on transition/cancel/attempt writes | SH07 (atomic admission/transition writes) |
| 6 | `reconcile_gateway_state` treats every queued/running record as orphaned | instance A destroys instance B's live requests | SH07 (ownership-aware recovery; step 0 interim visibility only) |
| 7 | `EventBus._correlation_chains` unbounded per-process growth | memory leak in a long-lived service | SH04 step 5 (bounded retention) |
| 8 | `_SESSION_RUNTIME` module singleton + daemon asyncio loop thread (agents_gateway_sessions.py:654) — sessions and owned ACP children die with the host process | sessions not shareable, not durable; orphan risk on host kill | AS08 (registry on control plane), AS17 (ManagedProcess), AS26 (orphan recovery) |
| 9 | Session store per-session `threading.Lock` registry (agents_gateway_sessions_store.py:47) | cross-process turn-serialization races | AS08 (turn serializer on control plane) + SH07 write discipline |
| 10 | Dispatch workers are daemon threads in the submitting process (RV511): capped wait + caller exit kills work mid-attempt, stranding 'running' records | silent work loss; stale running records | SH04 (service owns active work; submission/client exit cannot terminate a worker), SH07 step 0 characterizes |
| 11 | AS18 `agents.turn.*` / `agents.session.*` events publish on the in-process EventBus only | cross-process observers see nothing | AS08/AS09 (shared control-plane event path / FileEventStore or approved transport adapter), SH09 (durable external triggers) |
| 12 | Gateway store rooted at `<project>/.audiagentic/runtime/agent-llm-gateway` (agents_paths.py) — store home = submitting project | machine-wide service needs a state home + per-project record scoping | SH02 (manifest/canonical roots) + SH04 (service state home decision) |
| 13 | Component profile is process-global (VAL-COMP-010) | gateway service cannot switch profiles per job | SH06 (profile-per-worker isolation) |
| 14 | Provider config isolation is fixed/partial for several providers | concurrent jobs mutate shared user config | MA20 (isolation-tier fact) + SH06 (materialization strategy) |
| 15 | Dispatch reads implicit process env (e.g. `AUDIAGENTIC_GATEWAY_STREAM_OUTPUT`); submission context inherited from caller process | nondeterministic resolution; project bleed | SH02 (explicit envelope and frozen managed runtime digest); SH06 materializes provider-owned environment from managed configuration |
| 16 | Concurrency accounting (`pq.running`, planned `pq.llm_running`, `_TURNCB`) is in-memory per process | limits not machine-wide; lost on restart | SH04 (service-owned accounting), SH08 (machine-wide arbitration) |

## 5. Phase gates

Each phase has entry, exit, rollback, and deletion criteria. No phase starts
before its predecessor's exit gate.

| Phase | Item(s) | Entry | Exit | Rollback | Deletion |
| --- | --- | --- | --- | --- | --- |
| 0. Contracts | SH02 | SH01 review approved | versioned envelope + manifest schemas frozen; round-trip/redaction/cross-project tests green | n/a (additive) | — |
| 1. In-process seam | SH03 | SH02 frozen; AR25 enforced | existing suites pass at public boundary; conformance + architecture tests green; one control-plane owner | pure refactor — revert | direct internal callers of module singletons |
| 2. Standalone service (opt-in) | SH04 | SH03 done; PR05/PR06/PR07 available | two independent clients share one service; submitter exit does not kill work; restart recovery deterministic | config flag back to in-process | — |
| 3. Self-managed discovery | SH05 | SH04 proven | barrier-start single-winner; stale/forged record safety; version-skew explicit | manual service start remains | — |
| 4. Isolation + durability | SH06, SH07 | SH02 manifest + MA17 execution entry + MA20 tier facts (SH06); SH04 (SH07) | adversarial two-project gates; crash-injection at every transition; ownership-aware recovery replaces blanket reconcile | disable shared mode | `reconcile_gateway_state` destructive path |
| 5. Operations | SH08, SH09, SH10, AS08 | SH06/SH07 exits | arbitration load tests; durable event ingress; lease/drain/idle lifecycle; detached sessions | per-feature flags | — |
| 6. Cutover + deletion | SH11 | staged soak evidence on Windows+POSIX; documented rollback window | no production caller constructs the old owner; dependency scans green | exercised rollback before deletion | in-process backend, stale flags, shims, obsolete tests |

## 6. Ownership matrix (no duplicate ownership)

| Concern | Owner | Explicitly not |
| --- | --- | --- |
| Service transport, discovery binding, durable request ownership, admission/arbitration policy, cutover | shared-gateway (SH02–SH11) | agents, providers |
| Session registry, turn policy, attach/resume, session lifecycle events, observability projection | agents (AS08–AS26); AS21 projection feeds SH07 (RV561) | shared-gateway does not own session semantics |
| Execution entry, config materialization families, isolation-tier facts, capability declarations | providers (MA16/MA17/MA20; MA17 carries worker_id, attempt_epoch, isolation tier, reserved session ref per RV562) | no execution recipes; no requester knowledge |
| Reusable service records, client leases, ownership proof, start-or-attach, drain/stop, managed processes | foundation (PR05/PR06/PR07) | gateway-local discovery records, PID journals, startup locks are forbidden (AS08 files note) |
| Event transports (in-process bus, FileEventStore, future broker impl) | foundation; SH09 selects/binds behind EventBusProtocol | gateway core never imports a broker |
| MCP server process sharing | PR03 (separate plan) | not the agent gateway; may reuse the same PR05–PR07 primitives |

## 7. Compatibility and versioning policy

- Protocol negotiation at the gateway handshake (SH04 health/version/capability
  endpoints). Old clients receive a stable version error or a supported
  translation (SH02); never silent misinterpretation.
- Request/session records are schema-versioned (SH07); migrations are
  forward-only with explicit migration code.
- Gateway upgrade/version skew must not kill an unrelated active service
  (SH05 step 5).
- During phases 2–5, in-process vs standalone is explicit configuration; no
  automatic fallback that would create two silent authorities.

### 7.1 SH04 protocol binding

- The v1 origin is explicit `http://127.0.0.1:<port>`; remote hosts, wildcard
  binds, credentials in URLs, and implicit endpoint discovery are rejected.
- Every request uses a bearer token loaded from an explicit local token file.
  The service creates that file once with private POSIX mode where supported;
  the file path, not the token, is the durable auth reference.
- Health reports `gateway-service-v1`, the current owner epoch, and
  capabilities. Lease acquisition and every domain call carry the same
  protocol version. Domain calls additionally carry the current owner epoch
  and an active lease id; the service validates all three before invoking the
  gateway application.
- Health has one bounded retry for a transient transport failure. Lease
  attach/renew and domain mutations are not network-retried. A client may
  reattach once after an authoritative stale-lease rejection because the
  domain operation has not executed at that point.
- Project roots are resolved to absolute canonical paths by the client and
  rejected by the service if they are relative or non-canonical.

### 7.2 SH06 private worker protocol binding

- A disposable worker accepts one newline-delimited `gateway-worker-v1`
  `execute` frame on its private stdin and emits exactly one identity
  `handshake` followed by one terminal `result` or redacted `error` frame.
- Every frame binds `worker-id`, `attempt-epoch`, manifest id, context
  fingerprint, canonical project root, component-profile identity, and the
  evidence-backed isolation tier. Responses also bind the PID and OS process
  creation identity so PID reuse cannot satisfy the handshake.
- `execution-request` and `execution-result` are the exact MA17 public typed
  mappings. They are runtime-only and excluded from object representations;
  encoded frames, prompts, results, and raw errors are never logged or
  persisted. The request contract rejects environment, provider-config,
  credential, and secret side-channel fields.
- The outer worker identity must equal the inner provider request/result
  attempt identity. Unknown fields and protocol versions fail closed; there
  is no compatibility coercion or provider-name branch.

## 8. Security boundary

- Local machine only; the SH04 service binds exclusively to IPv4 loopback and
  requires bearer-token authentication. Remote/multi-machine access is a
  non-goal of this program.
- Per-project isolation is enforced by the SH02 schema and SH06 workers:
  canonical project roots and frozen managed runtime identity are in the
  schema; provider-managed configuration materializes the required environment
  and secrets at worker launch. Raw credentials and prompts never persist in
  gateway records (existing redaction standards apply to all new surfaces,
  SH08 status included). Multi-root workspaces require a later schema version
  only when an owning use case exists.
- Stale or forged discovery records cannot cause unsafe process termination
  (PR07 ownership verification, SH05).
- Unauthenticated or version-mismatched local clients are rejected (SH04).

## 9. Non-goals

- No remote/multi-machine gateway, TLS story, or network auth scheme.
- No change to provider execution semantics (MA17 owns the seam) or session
  semantics (AS owns them).
- No broker/vendor selection here — SH09 decides against requirements; MQTT
  is a candidate, not a conclusion.
- No speculative worker pooling: one-job/one-worker until pooling safety is
  proven per fingerprint (SH06).
- No permanent dual ownership: the migration obligation ends with deletion
  (SH11).

## 10. Sponsor review — decisions

Resolved 2026-07-17:

- **AR25 scheduling** — DECIDED: implement AR25 first, as its own
  arch-standards item, ahead of SH03. SH03 consumes its enforcement.
- **Service state home** — DECIDED: split ownership (see §2.1). Project-owned
  records stay in the project tree so a project can always see what is its
  own; the control plane keeps only its core service state and a rebuildable
  active-work index under the user home.
- **Continuous-service mode (SH10)** — DECIDED: self-managed mode first;
  service-manager adapters are a later, optional slice and are off the first
  cutover's critical path.

- **Design approval** — APPROVED 2026-07-17 (sponsor). SH01 closed; SH02
  schema freeze unblocked.

Foundation prerequisite status: PR05, PR06, and PR07 completed on 2026-07-17;
SH04 reuses their service record, lease, ownership, and guarded lifecycle APIs.

## Appendix A — v1 decision record (EDJ13, superseded)

Status: decided (v1) — 2026-07-12; superseded by v2 above on 2026-07-17.

The v1 record established: the events-only boundary between agent-jobs and
the gateway (enforced by `tests/unit/jobs/test_gateway_boundary.py`); the
original seven same-process assumption rows (now rows 1–7 of §4); retention
of blocking Python APIs as same-process conveniences; and deferral of
leasing/locking/reconciliation-guarding until a second gateway instance was
an approved requirement. All v1 "defer" rows are now owned by SH/AS/PR items
per §4; the v1 non-goals are dissolved into the phase gates of §5.
