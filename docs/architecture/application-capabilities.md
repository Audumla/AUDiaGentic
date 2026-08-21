# Application capabilities architecture standard

Status: **normative** for all production Rust code from `audiagentic-core` through reusable Application Capabilities. Provider, harness, AgentWork, Context, gateway, protocol, UI and distributed-runtime semantics remain above this line.

This document is the architecture contract for the locked layers. The goal is not to make the platform generic; it is to make the existing small layers hard to misuse.

## Locked layer model

```text
future application/domain authority
Context / AgentWork / gateway / harness / providers
                    |
==================== LOCK LINE ====================
                    |
reusable application capabilities
  events / workflow / time / managed-config
                    |
concrete host implementations
  host-native
                    |
narrow host contracts + authorities
  host
                    |
foundation libraries
  errors / config / sensitive / template / reconcile / file-store
                    |
core
  identity / Application<C> / execution+correlation identity / lifecycle / diagnostic projection
```

Dependencies point downward only. A lower layer must not know the application, provider, protocol, runtime, UI or transport that consumes it.

## Normative principles

### 1. Core stays capability-neutral

`audiagentic-core` remains zero-dependency and does not gain workflow, provider, configuration, logging, plugin, runtime or service-container semantics. `Application<C>` keeps composition opaque.

### 2. Raw configuration stops at composition

Configuration is a top-level operational principle, but raw configuration is not a capability API.

```text
raw sources
   -> ordered configuration resolution
      -> application-owned typed config
         -> narrow capability-owned policy
            -> capability
```

A semantic capability must not read files, discover project directories, read environment variables or receive an untyped configuration map. Source acquisition belongs to the application/host edge.

`audiagentic-config::ConfigLayers` resolves already-acquired TOML sources in explicit order and records a deterministic `ConfigRevision` plus source-layer identities. It performs no I/O. The revision identifies the exact ordered configuration inputs used for an execution; it is provenance, not a cryptographic digest.

### 3. Policy and authority are different

**Policy decides desired behaviour. Authority decides which external effects are permitted.**

Examples:

- `EventPolicy` controls local event retention behaviour.
- `ProcessRequest` describes requested process behaviour.
- `ProcessAuthority` controls which executable paths may actually be launched.
- `FileReadAuthority` / `FileWriteAuthority` control filesystem scope.

There is no universal `Policy` trait, policy registry, capability registry or DI container. A capability gets a named policy type only when it has meaningful variable behaviour.

### 4. Errors are domain-owned but public failure identity is stable

Every Rust error does **not** become a platform error. Internal/implementation errors remain local typed sources.

Errors that form part of a reusable capability/application boundary expose a stable `ErrorDefinition` through `CodedError`:

```text
stable code
canonical message
operator/developer resolution
```

Rules:

1. one code identifies one semantic condition;
2. one code has one canonical message;
3. variable values belong in typed error fields/details, not alternate messages;
4. codes use controlled categories (`VAL`, `CON`, `RES`, `IO`, `NET`, `TO`, `EXT`, `CFG`, `VER`, `INT`, `UNS`);
5. code shape is compile-time validated by `audiagentic-errors`;
6. error definitions are compiled with the owning capability rather than loaded from runtime configuration;
7. underlying source errors remain available through the Rust error chain when wrapping is appropriate;
8. public protocol envelopes are a later edge projection, not a foundation error base class.

The first locked coded boundaries are configuration, events, workflow, deterministic time identifiers and managed configuration. Native host/storage errors remain typed implementation sources until an application boundary intentionally projects them.

### 5. Observability is a design concern, not a platform service

AUDiaGentic will not create an observability manager, telemetry bus, generic `EventSink`, global logger or proprietary span model.

Operational instrumentation uses the Rust `tracing` ecosystem at meaningful application/runtime/effect boundaries. Semantic capability crates remain independent of a tracing backend.

When an execution authority exists, its root span must carry, where available:

- `execution_id`;
- `correlation_id`;
- effective `config_revision`;
- application/work identity owned by the higher layer.

Nested boundary spans/events should add operation-specific identities such as workflow id/revision, effect id, process id and stable error code.

Instrumentation belongs around meaningful operations such as configuration resolution, workflow application, managed-config application, process lifecycle and external I/O. Pure calculations do not need telemetry simply because tracing exists.

OpenTelemetry, JSON logs, rotating files, consoles or remote collectors are subscriber/exporter choices above these locked semantics and can be added later without changing capability APIs.

### 6. Domain events, diagnostics and execution output are different

```text
Domain event    durable/application-semantic evidence
Trace event     operational diagnostic evidence
Execution output externally consumable ordered result/progress
```

They may share execution/correlation identity but must not be collapsed into one universal event model.

`audiagentic-events` remains a typed caller-owned domain-event primitive and explicitly is not observability infrastructure.

Ordered execution output will be owned by the future execution authority above this lock line. We do not invent an output subsystem before that consumer exists.

### 7. External effects cross host boundaries

Application capabilities do not call native filesystem/process/network/secret APIs directly. Effects cross narrow host contracts with explicit authority.

`audiagentic-file-store` is a low-level durability implementation used by the native file host; higher application proofs must not bypass `FileHost` for managed state.

Process authority is launch authority, not a sandbox. Current native lifecycle ownership is for the direct child only. Descendant-tree containment remains an explicit future hardening requirement and must not be claimed before Unix process-group/session and Windows Job Object semantics are proven.

### 8. No code bleeding

The following are prohibited below the lock line unless a concrete architecture review changes this standard:

- provider/harness/session vocabulary in core/foundation/application primitives;
- service locators, DI containers, global registries or plugin managers;
- global event buses/workflow managers/timer runtimes;
- raw config/environment/filesystem discovery inside semantic capabilities;
- transport/protocol types inside reusable capabilities;
- tracing/OpenTelemetry dependency in pure semantic capability crates merely to obtain logs;
- arbitrary native file access by application capabilities;
- public claims stronger than the concrete host implementation proves.

## Layer-by-layer compliance

| Layer | Locked responsibility | Current assessment |
| --- | --- | --- |
| core | identity, opaque application composition, execution/correlation identity, generic lifecycle/diagnostic projection | GREEN; keep frozen |
| errors | stable public error definition vocabulary only | GREEN |
| sensitive | secret-safe values and metadata | GREEN |
| template | deterministic text transformation | GREEN |
| reconcile | pure observed/desired/plan/change/receipt semantics | GREEN |
| config | typed extraction + ordered in-memory source resolution + config revision; no source I/O | GREEN |
| file-store | low-level durable file replacement | GREEN; not an application storage API |
| host | narrow host contracts + explicit authority | GREEN for file/process; network/secret contracts remain provisional until consumers prove semantics |
| host-native | authority enforcement + direct-child lifecycle | GREEN within documented limits; descendant-tree ownership not claimed |
| events | ordered domain events, bounded retention/cursors, explicit `EventPolicy`; no broker/telemetry | GREEN |
| workflow | deterministic state transition/effects/snapshots; no runtime/I/O | GREEN |
| time | deterministic caller-supplied time/deadline/timer-set semantics | GREEN |
| managed-config | single-writer observe/plan/apply over `FileHost` + reconcile | GREEN |

`NetworkHost` and `SecretHost` remain intentionally provisional declarations. They are not permission to build provider semantics below the lock line. If a real consumer proves a different contract, they may be reshaped before provider work is declared production-ready.

## Application composition proof

The platform proof demonstrates the intended flow without introducing a manager:

```text
ordered raw config layers
    -> typed PlatformConfig
    -> PlatformPolicy
        -> EventPolicy

ExecutionContext
    execution_id + correlation_id

PlatformComposition
    policy + explicit host facilities + authorities
        -> managed config
        -> event stream
        -> workflow
        -> timer set
        -> owned process
```

The proof keeps `ConfigRevision` available next to `ExecutionContext`. A future executable may place those values into a `tracing` execution span without changing any semantic capability contract.

## Architecture gates

`scripts/rust-foundation-smoke.sh` is part of this standard. In addition to formatting, Clippy, tests, executable proofs and dependency direction, it must enforce:

- `audiagentic-errors` has zero normal dependencies;
- coded application-capability boundaries depend only on the small error-definition crate in addition to their legitimate semantic dependencies;
- stable error-code definitions are unique across the locked boundary crates;
- raw filesystem/environment access does not enter semantic capability crates;
- config does not become a file/environment discovery subsystem;
- events/workflow/time/managed-config do not depend on config or native-host implementations;
- no custom telemetry/event/workflow/timer/service manager vocabulary enters the locked layers;
- the policy proof remains explicit (`ConfigLayers -> typed config -> EventPolicy`);
- application state I/O continues through host/capability boundaries.

## Deliberately above this standard

The following stay above or after this lock until a concrete consumer proves them:

- Context / AgentWork / canonical gateway execution authority;
- harness/provider implementations and provider-native sessions;
- descendant process-tree containment;
- durable event broker/store;
- workflow scheduler/retry/recovery coordinator;
- multi-writer/CAS managed configuration;
- ordered execution-output contract;
- artifact abstraction;
- OpenTelemetry/exporter configuration and metrics;
- MCP / ACP / A2A / ASA / AGNTCY / Discord / UI projections;
- WIT/Wasm/Bevy runtime choices.

Any change below the lock line must keep the Rust architecture contract green on Ubuntu, macOS and Windows. Higher layers may build on these contracts but must not weaken them implicitly.
