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

## Protocol message acceptance (stage 4: SH43)

The existing owner must atomically accept authorized message identity, payload
reference/digest, immutable target and dispatch intent before any native effect.
Replay returns the original acceptance; changed payload conflicts. Secondary
input/queue projections recover from that acceptance. Select the public API and
crash-safe persistence mechanism during SH43 implementation using existing owner
ports and writers, not a second authority. Multiple filesystem renames are not
one atomic transaction. A committed acceptance must reference durable input.

These protocol continuation requirements do not gate stage 1's existing gateway
request API. Stage 1 still preserves its durable request admission, terminal proof
and no-blind-replay requirements.

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

Use a concrete configured authentication profile for remote ingress, not a new
general identity/delegation framework. When using externally issued access
tokens, validate configured issuer, exact resource audience, algorithms,
signature keys/rotation and expiry; never accept arbitrary JWTs. Node enrollment
uses its own service identity/credential and workspace grants; never forward a
user's provider credential to a node or treat a proxy header as identity unless
the configured front door overwrites it and backend access is restricted.

Revalidation points are owner acceptance commit, FIFO reservation/dispatch-intent,
node command acceptance and immediately before native effect. Freeze target
generation/node epoch and command payload digest in the authorized command.
Disconnected or stale nodes cannot obtain new sends. Revocation blocks new
central admissions and dispatch permissions immediately. Already accepted native
work continues to be observed with output restricted; no silent shared interrupt.

For stages 2/3, native effects require command-scoped authorization bound to the
authenticated node epoch, target generation, payload digest and grant revision.
Reuse authorized dispatch if it provides the required revocation ordering; add a
separate confirmation exchange only if a demonstrated requirement needs it. No
offline grant leases, cross-machine clock protocol or consensus is introduced.
Disconnected nodes receive no new dispatch authority. Reconnect requires current
authorization and exact command evidence before another effect.

Record the authorization linearization point and revocation race honestly:
revocation blocks later authorization, but cannot undo already authorized or
native-accepted work during a partition. Observe accepted work without silently
interrupting shared human work. Node-specific contracts do not gate stage 1.

## Gateway and node durability boundaries (stages 2/3)

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

These rows are durable facts and ordering constraints, not mandatory separate
transactions, acknowledgements or public lifecycle states. Combine records when
there is no intervening effect and the same crash-safety guarantees hold.

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

Audit changed imports, configured registrations and composition paths for owner
boundary compliance at the shipped stage. CLI/MCP/A2A/ACP/service adapters use
owner ports; Providers stay requester-blind; foundation holds neutral contracts.
No second store, scheduler, callback bus or generic gateway facade is justified.
Use an exact checkout; no particular reviewer host is a release prerequisite.

Measure startup/resource use and admission/dispatch overhead against a stated
baseline for the topology being shipped. Broader percentile, replay, probe, lock
and WAL benchmarking is follow-up unless a measured regression or explicit
release target requires it. Do not add a benchmark framework or speculative
optimization as a universal delivery gate.

Structural gates are already concrete: pure help starts no application/browser;
no lock spans a native effect or human approval; buffers/frames/replay windows are
bounded; default status omits transcripts/diagnostics/history; native payloads
are not duplicated as central transcripts. Cache Provider-owned static facts only
if measured cost warrants it, keyed by binary/adapter/platform/config/evidence
identity and invalidated on change, using the owning cache seam. Live
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

This addendum scopes qualification to the advertised feature and does not
authorize runtime implementation. Implementation review validates applicable
transaction, authorization and recovery invariants. Wire qualification and native
attachment evidence remain scoped to the corresponding release stage.
