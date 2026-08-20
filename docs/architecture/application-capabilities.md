# Application capability layer

This layer adds reusable application-building semantics above the frozen Rust production foundation. It is intentionally small: it does not introduce a global runtime, service registry, generic plugin container, or transport framework.

## Layer placement

```text
application / domain composition
        |
        +---- domain capabilities
        |       provider sessions
        |       managed work / agent work
        |       planning / release / audit
        |       application-specific workflows
        |
        +---- reusable application capabilities
        |       audiagentic-events
        |       audiagentic-workflow
        |
        +---- concrete host implementations
        |       audiagentic-host-native
        |          NativeFileHost
        |          NativeProcessHost
        |
        +---- narrow host contracts
        |       audiagentic-host
        |          FileHost
        |          ProcessHost -> owned ProcessChild
        |          NetworkHost (provisional)
        |          SecretHost (provisional)
        |
        +---- foundation libraries
        |       config / template / reconcile / sensitive / file-store
        |
        +---- audiagentic-core
```

The distinction is load-bearing: workflow and event semantics are application capabilities; operating-system process creation is a host facility. A workflow may emit an application-defined effect such as `LaunchHarness`, but it does not launch a process itself.

## Event capability

`audiagentic-events` provides:

- typed `EventId`, `EventStreamId`, and `CausationId`;
- `EventEnvelope<E>` with correlation, causation, and monotonic stream sequence;
- caller-owned `EventStream<E>` for ordered in-memory evidence and polling/projection inputs.

It deliberately does **not** provide a singleton event bus, global subscriber registry, queue abstraction, retry policy, durable broker, or telemetry system. Domain event payloads remain domain-owned. Delivery semantics are proven later by the consumer that needs them.

This lets applications build event-driven behavior without prematurely deciding that local channels, MQTT, NATS, Kafka, durable streams, MCP streaming, or another transport is the universal answer.

## Workflow capability

`audiagentic-workflow` is a pure deterministic state-machine primitive:

- application-owned state, input, and effect types;
- deterministic `WorkflowDefinition::decide`;
- `Continue`, `Complete`, and domain-failure transitions;
- monotonic workflow revisions;
- stale-revision rejection for optimistic coordination;
- receipts containing the new revision, status, and emitted effects.

The workflow crate does no I/O and owns no scheduler. Effects are data interpreted by the application. Persistence can use file/database capabilities; process effects can use `ProcessHost`; events can be recorded in `audiagentic-events`; remote triggers can later arrive through MCP/A2A/ASA/AGNTCY adapters.

Retries, timers, cron, compensation, durable queues, fan-out/fan-in, distributed leases, and DAG semantics are intentionally not universalized yet. They should be added as separately proven capabilities when real applications establish the required semantics.

## Managed process host

The previous speculative one-shot `ProcessHost::run()` shape is replaced by an owned lifecycle:

```text
ProcessHost::spawn(authority, request) -> ProcessChild

ProcessChild
  id
  stdin / stdout / stderr
  try_wait
  wait
  kill
```

`ProcessRequest` defaults to a cleared environment and requires explicit secret-wrapped environment values. Debug output exposes environment keys but never values. `ProcessAuthority` is an executable allow-list enforced by the concrete native host through canonical executable paths.

`NativeProcess` owns and reaps the child. Dropping a live child performs best-effort kill + wait so direct children are not knowingly abandoned by the host object.

### Current process-boundary limit

This proof owns the **direct child**, not a complete descendant process tree. That distinction is explicit. A provider harness that can spawn grandchildren must not be declared production-complete until a consumer proves cross-platform descendant cleanup semantics (for example Unix process-group/session ownership and Windows Job Object ownership). The contract is intentionally shaped so this strengthening can happen in the concrete native host without pushing provider semantics into core or workflow.

`ProcessAuthority` is also launch authority rather than a sandbox. A started native process still has the OS-account authority available to it unless a stronger platform sandbox is applied.

## Composition proof

`examples/capability-app` proves the layers together without a manager object:

1. a deterministic workflow transitions `Pending -> Running` and emits `Record(Started)` plus `LaunchChild` effects;
2. the application records the domain event through its caller-owned typed event stream;
3. the application interprets `LaunchChild` through `NativeProcessHost`;
4. the child is the same executable in a special harness-like mode, making the proof shell-free and cross-platform;
5. the parent writes through child stdin, reads the response from stdout, confirms the process is still alive, kills/reaps it, and records the observation as a domain event;
6. the workflow transitions to `Completed` and emits the final event.

This demonstrates the target architecture: semantic capabilities coordinate effects, host facilities perform OS work, and the application owns composition.

## Next capability candidates

The next reusable capabilities should be added only with concrete consumers. The strongest candidates are:

- managed-process **tree** ownership and graceful-stop escalation for real agent harnesses;
- durable event-store adapter and bounded cursor reads once a standalone consumer exists;
- timer/deadline capability for workflows that genuinely require temporal semantics;
- managed configuration reconciliation built on `audiagentic-reconcile` + `FileHost`;
- provider-neutral Context/AgentWork orchestration above provider-private session generations;
- outer ACP/A2A/ASA/AGNTCY/MCP projections over those application capabilities.

None of those require widening `audiagentic-core`.
