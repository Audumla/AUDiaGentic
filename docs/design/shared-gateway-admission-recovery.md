# Shared gateway: admission and recovery decisions

Planning addendum to SH37-SH43, following the deeper industry/agent standards
audit. These are proposed implementation contracts, not implemented APIs or a
claim of wire/native qualification. The canonical topology remains in
[Shared gateway execution contract](shared-gateway-execution-contract.md).

## Standards baseline and applicability

Primary references checked on 2026-10-26:

| Reference | Planning disposition |
|---|---|
| [A2A released 1.0.0](https://a2a-protocol.org/v1.0.0/specification/) | Target a version-pinned 1.0 interface; SDK/module labels are not conformance proof. Do not repeat the audit's unverified 1.0.1 assertion. |
| [ACP v1](https://agentclientprotocol.com/protocol/v1/overview) | Qualified v1 operations/capabilities; v2 remains draft and a future reassessment. |
| [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28) | Current official reference, not a claim that the installed SDK implements it. Pin the actual negotiated SDK/peer contract in qualification. The audit's 2025-11-25 reference is historical. |
| [MCP HTTP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) | Applies if exposing an HTTP MCP surface; do not impose that flow on local stdio or confuse it with internal node transport. |
| [OAuth security BCP](https://www.rfc-editor.org/rfc/rfc9700), [JWT BCP](https://www.rfc-editor.org/rfc/rfc8725) | Validate deployed token and delegation profile; transport encryption alone is not authorization. |

A2A SendMessage configuration section 3.2.2 governs execution mode: default
waits for terminal/interrupted Work; explicit returnImmediately permits an
in-progress response. Waiting occurs through owner events outside mutation locks.
Do not infer default immediate acknowledgement from a general async description.
Unsupported versions/capabilities use the selected binding's defined errors.
No legacy interface is silently added to accommodate a missing version header.

Keep a version-to-tests table in SH42 evidence with exact specification URL,
schema revision, SDK/client versions and supported operations. A newer stable
specification triggers review, not an automatic migration or support claim.

## One canonical message acceptance operation

Extend the owning Agents application and injected GatewayClient ports, not
protocol adapters or a new task facade. Proposed operation shape:

```python
receipt = owner.accept_protocol_message(
    authenticated_principal=principal,  # transport-verified, never model text
    agent_id=agent_id,
    context_id=context_id,
    existing_work_id=task_id,           # optional; continuation retains Work
    message_identity=message_identity,
    payload_reference=protected_input,
    expected_target_generation=generation,
)
```

The owner normalizes these fields before mutation. In one owner acceptance
transaction it verifies grants, Agent Definition, Context/Work relationship,
current lifecycle, immutable execution target and message identity/fingerprint.
The primary committed acceptance contains the canonical Work/message identity,
payload digest/reference, target generation, stable command identity and dispatch
intent. Its commit is the acceptance linearization point. No native action can
precede it. Input indexes and queue projections are recoverable from that owner
record, not independent acceptance authorities.

Implement under the existing WorkStore lock/revision mechanism, with one atomic
authoritative acceptance record. Current append_work_input plus a separate Work
write is insufficient. Do not pretend multiple filesystem renames are one atomic
transaction. Resolve the precise record/schema migration and crash-safe writer
inside SH43 before coding; reuse the existing owner rather than adding a registry.
Protected content staging before acceptance may leave an unreferenced artifact,
which owner retention may reclaim. A committed acceptance must never reference
an artifact that was not durably made available first.

Replay key is authenticated issuer/subject plus Context/target and protocol
message identity. Same key and fingerprint returns the original receipt; changed
payload conflicts; distinct messages with identical text stay distinct. Exclude
new server timestamps from payload equality. For ACP without an application
replay identity, assign a distinct owner command ID; do not infer retries from
text or blindly replay after disconnection.

Existing-task A2A input keeps Work identity and validates continuation state.
Context-only new input creates distinct Work. A committed message with a missing
gateway queue projection is repaired using the same command/request identity.
It is not accepted a second time. Gateway admission must support this explicit
owner idempotency field rather than a reserved generic metadata alias. Lock scope
ends before provider I/O, waits, human approval or network response serialization.

Default A2A wait, explicit immediate response and ACP outstanding prompt turn all
read that same owner state. Client transport timeout/disconnect does not mark
accepted native work failed or cancel shared human work. Map terminal/interrupted
outcomes honestly; successful end_turn cannot stand in for uncertain delivery.

## Identity, grants and effect boundaries

The authorization resource tuple is:

```text
issuer/subject + optional verified delegated-subject
project + Agent Definition + Context/Work + action
node/workspace + gateway session/binding generation + grant revision
```

No caller-provided principal/delegation/native locator overrides trusted context.
Bind delegated authority to an explicit configured issuer and permitted subject;
otherwise reject delegation. Gateway operator, observer, submitter and
cancel-own-request privileges are distinct. A task/context/session ID is not an
authorization token. Grants must be checked on reads/cards/output as well as Send.

Choose a validated external identity-provider access-token profile for remote
client ingress: configured issuer, exact resource audience, explicit algorithms,
signature keys/rotation and expiry, with no accept-any JWT mode. Node enrollment
uses its own service identity/credential and workspace grants; never forward a
user's provider credential to a node or treat a proxy header as identity unless
the configured front door overwrites it and backend access is restricted.

Revalidation points are owner acceptance commit, FIFO reservation/dispatch-intent,
node command acceptance and immediately before native effect. Freeze target
generation/node epoch and command payload digest in the authorized command.
Disconnected or stale nodes cannot obtain new sends. Revocation blocks new
central admissions and dispatch permissions immediately. Already accepted native
work continues to be observed with output restricted; no silent shared interrupt.

Initial node mode requires online per-command grant confirmation immediately
before native admission. Bind the confirmation to command, authenticated node
connection epoch, target generation, payload digest and grant revision. It grants
one admission, not permission to issue later prompts. Do not add offline grant
leases, cross-machine expiry clocks or distributed consensus in the MVP.
Connection loss invalidates an unused confirmation; reconnect requires a new
decision and exact command evidence before effect. Already accepted native work
continues offline under existing observation/recovery semantics.

Grant confirmation is the authorization linearization point for that command.
Revocation blocks later confirmations, but cannot promise to undo an already
confirmed/native-accepted operation in the gap before the next remote observation.
Node checks received cancellation/revocation and owner/generation fences before
effect. Record this ordering honestly rather than promise instantaneous global
revocation during a partition. Measure the additional confirmation round trip;
introduce a bounded lease only through a later justified plan if it is necessary.

## Gateway and node durability boundaries

Gateway owns canonical Work/request/FIFO and command identity. Node owns native
effect WAL/receipt evidence. Their records are not a distributed atomic database.

| Ordered boundary | Durable fact and recovery rule |
|---|---|
| Gateway acceptance | Commit owner message and dispatch intent before scheduling; repair missing projection by same identity |
| Gateway command send | Preserve command, target generation, node epoch and authorization revision before transmission |
| Node prepared | Persist command deduplication record and payload reference before acknowledging preparation |
| Node effect intent | Durable write before native admission; a crash after this boundary is potentially ambiguous |
| Native accepted | Persist exact native receipt/turn correlation before reporting acceptance centrally |
| Observed terminal | Verify request-specific output, persist evidence/artifact, then central completion |

Document/test persistence barriers, not just atomic rename: critical pre-effect
intent and receipts need the selected platform's durable-write guarantee.
Observational timeline batching must never weaken those barriers. Use owning
writers and existing neutral I/O facilities, not ad hoc JSONL or another journal
framework. A node WAL is transactional evidence; the gateway remains authority.

After lost connection, query the same command under fresh authenticated epoch
and generation fences. Prepared with positively absent effect intent may proceed
only after renewed authorization. Effect intent without a definitive receipt is
uncertain; no resubmit unless native idempotency/queryable exact evidence proves
safety. Definitive receipt/result can reconcile the original request. Expiry of a
reconciliation deadline releases compute reservation honestly but does not clear
the uncertain delivery or target fence. Retain uncertainty until definitive
evidence or explicit operator disposition.

Queue waiting, command preparation, native acceptance, execution inactivity,
observer outage and client keepalive are separate clocks. A heartbeat cannot
renew genuine work progress. No generic retry loop around a native Send.
Retention never deletes active/uncertain/unacknowledged recovery evidence merely
because terminal request history or daily logs reach a count/age limit. After
central acknowledgement and resolution, compact receipts under the owner policy.

## Architecture and efficiency evidence gates

The full dependency audit remains required. Trace static imports, configured
adapter registrations and composition wiring from a clean exact checkout. Check
that inbound CLI/MCP/A2A/ACP/service adapters depend on owner ports, Providers
remain requester-blind, and foundation contains only neutral reusable contracts.
No second task/session store, scheduler, callback bus or general gateway facade.

Performance hypotheses are unmeasured until qualification. SH37/SH42 collect
cold/warm startup wall time, imports/RSS and initializer counts; admission and
queue-to-send p50/p95/p99; payload bytes; command/receipt latency; reconnect/replay
cost; native probe counts; lock hold/wait time and WAL durability overhead.
Compare identical local baseline and shared topology under declared OS/resources,
same-machine/two-machine placement and concurrent client counts. Non-model
transport load tests must be labelled separately from paid/native generation.
Freeze regression tolerances from those baselines before optimizing sensitive
paths; do not invent benchmark results or call a proposed target compliance.

Structural gates are already concrete: pure help starts no application/browser;
no lock spans a native effect or human approval; buffers/frames/replay windows are
bounded; default status omits transcripts/diagnostics/history; native payloads
are not duplicated as central transcripts. Cache Provider-owned static facts by
binary/adapter/platform/config/evidence identity and invalidate on change. Live
authorization, generation and effect readiness still revalidate at boundaries.
Do not add a global cache component or cache security decisions indefinitely.

## Future specification watchlist

| Owner | Trigger | Required action |
|---|---|---|
| SH43 | Stable A2A change to message/task/wait/security/schema | Pin revision, update wire mapping and negative/real-client tests |
| SH43 | ACP v2 stable plus supported SDK/client evidence | Deliberate owner migration; no draft capability advertisement |
| SH37/SH42 | Stable MCP transport/auth/capability change | Assess exposed transport and SDK/peer negotiation; optional task support reuses canonical Work |
| SH37 | Token-profile/identity-provider/security BCP change | Reassess audience/delegation/revocation and deployment tests |
| SH38/SH40 | Node channel security advisory or receipt/fencing defect | Update bounded channel/WAL compatibility and crash matrix |
| SH41 | Actual native harness binary/schema/integration change | Invalidate stale proof and requalify before admission |

This addendum does not remove qualification gates or authorize runtime work.
The next independent review must verify the exact isolated checkout, primary
specifications and transaction/grant/recovery contracts, rather than infer
implementation readiness from earlier design-only approvals.
