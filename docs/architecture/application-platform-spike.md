# Application platform capability spike

This spike turns the first application-capability proof into a broader application-building substrate while preserving the thin AUDiaGentic doctrine. It does not widen `audiagentic-core`, create a global runtime/container, or select a universal transport.

## Layer placement

```text
application / domain composition
        |
        +---- domain capabilities
        |       provider sessions / AgentWork / Context / audit
        |
        +---- applied application capabilities
        |       managed configuration
        |
        +---- reusable semantic capabilities
        |       events + bounded cursor pages
        |       deterministic workflow + snapshots
        |       deterministic deadlines/timer sets
        |       reconciliation create/replace/delete planning
        |
        +---- concrete host implementations
        |       native filesystem
        |       native owned child process
        |
        +---- narrow host contracts + authority
        |       filesystem read/write/remove
        |       process spawn/stdio/wait/kill
        |       network [provisional]
        |       secrets [provisional]
        |
        +---- foundation libraries
        |       config / template / sensitive / file-store
        |
        +---- audiagentic-core [frozen thin]
```

The layers are ownership boundaries, not a mandate to create a framework object for each box.

## Capability reassessment

| Capability | Assessment after spike | Architectural owner |
| --- | --- | --- |
| application identity / `Application<C>` | proven; freeze | core |
| execution/correlation identity | proven; freeze | core |
| generic lifecycle/diagnostic projection | proven; keep generic | core |
| secret/redaction value semantics | proven | sensitive foundation |
| typed config extraction/schema | proven; application still owns schema | config foundation |
| durable atomic file writes | proven | file-store foundation |
| reconciliation | strengthened to presence-aware create/replace/delete; still pure | reconcile semantic foundation |
| filesystem host | strengthened with optional read and remove required by a real managed-config consumer | host + native host |
| process authority | useful structural launch grant; explicitly not a sandbox | host |
| process lifecycle | strengthened with stdio policy and transferable owned handles; direct-child cleanup only | host + native host |
| descendant process-tree ownership | not yet proven; defer to real Pi/OpenCode/Codex/Claude harness proof | native host hardening |
| network authority/host | provisional; no expansion in this spike | host, pending consumer |
| secret retrieval host | provisional; no expansion in this spike | host, pending consumer |
| events | strengthened with bounded retention, explicit cursor expiry and bounded pages; still no broker | event capability |
| durable event store/broker | deferred: persistence/CAS/concurrency semantics not yet proven | future adapter/application capability |
| workflow | strengthened with snapshots/recovery; still deterministic and I/O-free | workflow capability |
| scheduling/time | deterministic timestamp/deadline/timer-set semantics added; caller supplies time | time capability |
| scheduler/cron/task runtime | deliberately absent | future runtime/application edge |
| managed configuration | now a concrete applied capability over reconciliation + FileHost | application capability |
| provider-neutral Context / AgentWork | still the next domain/application authority layer | application domain |
| ACP/A2A/ASA/AGNTCY/MCP | remain projections/adapters over application authority | outer edge |
| Tokio / Bevy / Wasmtime / wash | remain implementation choices outside foundation | optional runtime/component layer |

## Event paging semantics

`EventStream<E>` remains caller-owned. It can now be configured with a non-zero retention bound. Sequence numbers remain monotonic even when old events are evicted. `EventCursor` identifies the last consumed sequence and `page_after(cursor, limit)` returns a bounded page plus the next cursor and `has_more`.

A cursor whose next expected sequence has already been evicted fails explicitly with `CursorExpired`; a cursor beyond the current stream fails with `CursorAhead`. The primitive does not silently reset the caller to the oldest available event. This is suitable for bounded in-memory projections and polling but is not advertised as durable event sourcing.

## Workflow recovery semantics

`WorkflowSnapshot<S>` captures workflow identity, revision, status, and application-owned state. `WorkflowInstance` can be restored exactly from that snapshot. The workflow crate still does not serialize, persist, schedule, retry, or publish anything. Applications choose the persistence representation and storage capability.

## Deterministic time semantics

`audiagentic-time` introduces only semantic time values: `Timestamp`, `Deadline`, `TimerId`, and caller-owned `TimerSet`. Callers explicitly supply `now`. Due timers have deterministic ordering, and draining due timers is a pure state transition. Sleeping, wall clocks, cron, async tasks and durable scheduling remain outside this crate.

## Managed configuration

`audiagentic-managed-config` is the first applied reusable capability in this layer. It composes:

- `FileHost` observation and effects;
- `FileReadAuthority` / `FileWriteAuthority`;
- presence-aware reconciliation plans;
- explicit ownership/effect identities;
- receipts for create/replace/delete/no-op application.

It owns no global config registry, parser, filesystem watcher, scheduler or retry loop. It is currently a single-writer primitive; applications that need multi-writer correctness must add a storage boundary with real compare-and-swap/transaction semantics rather than pretending filesystem observation + write is CAS.

## Process lifecycle hardening

`ProcessRequest` now has explicit pipe/null/inherit policy for each standard stream. `ProcessChild` retains borrowed stream access and also supports transferring ownership of piped handles so harness adapters can place readers/writers on their own threads or reactors without making an async runtime part of the host contract. `close_stdin` and `is_running` are convenience lifecycle operations over the same owned child.

This still proves only direct-child ownership and reaping. Complete descendant-tree containment remains a separate cross-platform proof.

## Large composition proof

`examples/platform-app` exercises the capabilities through an opaque `Application<PlatformComposition>`:

1. create managed configuration through observe/plan/apply;
2. create a bounded event stream;
3. start a deterministic workflow and snapshot/restore it;
4. interpret an emitted timer effect into a caller-owned `TimerSet`;
5. interpret a launch effect through `NativeProcessHost`, transfer stdin/stdout ownership, perform a round trip, verify liveness, then kill/reap;
6. drain a due timer using explicitly supplied semantic time;
7. replace and re-read managed configuration;
8. complete the workflow;
9. prove stale event cursors fail and bounded paging advances correctly;
10. delete managed configuration and verify absence.

This is the intended platform shape: the application composes semantics, authorities and effects; no universal manager object coordinates them.

## Deferred on purpose

The following are not missing accidentally:

- durable event broker/store and distributed subscriptions;
- filesystem CAS/multi-writer managed-config transactions;
- cron/retry/scheduler runtime;
- complete process-tree containment;
- concrete network and secret hosts;
- provider/harness semantics;
- ACP/A2A/ASA/AGNTCY/MCP transports;
- WIT/Wasm/Bevy runtime choices.

Each belongs in a later proof with a real consumer and explicit correctness requirements.

## Next architectural slice

With these application-building primitives proven, the next large domain slice should move upward rather than make the foundation generic-er: canonical Context + durable AgentWork + gateway execution authority, with one real harness adapter consuming managed process lifecycle. That slice can establish the process-tree requirements and durable work/event projections needed before outer protocol surfaces are added.
