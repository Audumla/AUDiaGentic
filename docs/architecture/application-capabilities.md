# Application capabilities architecture standard

Status: **normative** for all production Rust code from `audiagentic-core` through reusable Application Capabilities. Provider, harness, AgentWork, Context, gateway, protocol, UI and distributed-runtime semantics remain above this line.

This contract locks only concepts that current code proves. The rule is deliberately asymmetric: a missing future abstraction is cheaper than a premature abstraction that every later capability must work around.

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
proven narrow host contracts + authorities
  file / process
                    |
foundation libraries
  errors / config / sensitive / template / reconcile / file-store
                    |
core
  application identity / execution+correlation identity / Application<C>
```

Dependencies point downward only. Lower layers do not know the application, provider, protocol, runtime, UI or transport that consumes them.

## Normative principles

### 1. Core stays capability-neutral

`audiagentic-core` remains zero-dependency and contains only application/execution identity plus opaque `Application<C>` composition. It does **not** predeclare capability/component IDs, lifecycle state, diagnostics, workflow, provider, configuration, logging, plugin, runtime or service-container semantics.

Adding an unrelated application or capability must not require modifying core.

### 2. Raw configuration stops at composition

Configuration is a top-level operational principle, but raw configuration is not a capability API.

```text
raw sources acquired at edge
   -> ordered ConfigLayers
      -> ResolvedConfig<T>
           typed value
           ConfigRevision
           ordered layer identities
         -> application-owned composition
            -> narrow capability-owned policy
               -> capability
```

A semantic capability must not read files, discover project directories, read environment variables or receive an untyped configuration map. `audiagentic-config` does not enable Figment environment acquisition and exposes no provenance-discarding convenience extraction API.

`ConfigRevision` identifies the exact ordered configuration inputs used for composition. It is deterministic provenance, not a cryptographic digest.

### 3. Policy and authority are different

**Policy decides desired behaviour. Authority decides which external effects are permitted.**

Current examples:

- `EventPolicy` controls local event retention behaviour.
- `ProcessRequest` describes requested child-process behaviour.
- `ProcessAuthority` controls which executable paths may actually be launched.
- `FileReadAuthority` / `FileWriteAuthority` control filesystem scope.

There is no universal `Policy` trait, policy registry, capability registry or DI container. A capability gets a named policy type only when it has meaningful variable behaviour.

### 4. Host contracts are earned by consumers

The locked host layer currently exposes only filesystem and direct-child process contracts because those are the effects exercised by current capabilities/proofs.

There is no speculative `NetworkHost`, `SecretHost`, async host future abstraction, or universal host-services container. Network, secrets and other effects will receive contracts only when a real higher-layer consumer proves the operations, authority model, error semantics and sync/async boundary that are actually required.

Process authority is launch authority, not a sandbox. Descendant-tree containment remains future work until Unix process groups/sessions and Windows Job Objects (or equivalent) are implemented and proven.

### 5. Errors are domain-owned but reusable failure identity is stable

Every Rust error does **not** become a platform error. Errors remain typed and owned by the domain that understands them.

Errors crossing a locked reusable capability boundary expose an `ErrorDefinition` through `CodedError`:

```text
stable code
machine category derived from the code prefix
canonical message
operator/developer resolution
```

Rules:

1. one code identifies one semantic condition;
2. one code has one canonical message;
3. dynamic values belong in typed error fields/details, not alternate canonical messages;
4. categories are controlled by the code prefix (`VAL`, `CON`, `RES`, `IO`, `NET`, `TO`, `EXT`, `CFG`, `VER`, `INT`, `UNS`);
5. code shape and category are validated by `audiagentic-errors`;
6. definitions are compiled with the owning capability rather than runtime-loaded;
7. underlying source errors remain available through the Rust error chain when wrapping is appropriate;
8. stable definitions are unique across the locked boundary crates;
9. public protocol envelopes are later edge projections, not a universal error base class.

Configuration, events, workflow, deterministic-time identifiers and managed configuration are coded boundaries. Managed-config now wraps host failures consistently on both observe and apply paths under stable capability-level identity.

### 6. Observability is a design concern, not a platform service

AUDiaGentic does not create an observability manager, telemetry bus, generic `EventSink`, global logger or proprietary span model.

Operational instrumentation uses Rust `tracing` at meaningful application/runtime/effect boundaries. Semantic capability crates do not depend on a telemetry backend and never install a subscriber.

A scoped application-edge proof owns `tracing` and `tracing-subscriber` and verifies a structured `application.execution` span carrying the canonical fields:

- `execution_id`;
- `correlation_id`;
- `config_revision`.

Meaningful nested operational events/spans may later add workflow/effect/process identity and stable `error_code`. Sensitive values must never be trace fields.

OpenTelemetry, JSON formatting, files, consoles, collectors, sampling and metrics remain runtime/subscriber/exporter choices above these semantic contracts.

### 7. Domain events, errors, telemetry and execution output are different

```text
Domain event      application-semantic evidence
Stable error      reusable failure identity + typed detail
Trace event/span  operational diagnostic evidence
Execution output  externally consumable ordered result/progress
```

They may share execution/correlation identity but must not be collapsed into one universal event model.

`audiagentic-events` remains a typed caller-owned domain-event primitive and explicitly is not observability infrastructure. Ordered execution output stays above this lock until the future execution authority proves its consumer contract.

### 8. External effects cross host boundaries

Application capabilities do not call native filesystem/process APIs directly. Effects cross narrow host contracts with explicit authority.

`audiagentic-file-store` is a low-level durability implementation used by the native file host; higher application proofs do not bypass `FileHost` for managed state.

### 9. No code bleeding

The following are prohibited below the lock line unless a concrete architecture review changes this standard:

- provider/harness/session vocabulary in core/foundation/application primitives;
- service locators, DI containers, global registries or plugin managers;
- global event buses/workflow managers/timer runtimes;
- raw config/environment/filesystem discovery inside semantic capabilities;
- transport/protocol types inside reusable capabilities;
- tracing/OpenTelemetry dependency in pure semantic capability crates;
- subscriber ownership in libraries;
- arbitrary native file access by application capabilities;
- speculative host contracts without a real consumer;
- public claims stronger than the concrete implementation proves.

## Layer-by-layer compliance after drift sweep

| Layer | Locked responsibility | Assessment |
| --- | --- | --- |
| core | application identity, execution/correlation identity, opaque `Application<C>` | GREEN; reduced to proven concepts |
| errors | stable code/category/message/resolution vocabulary only | GREEN |
| sensitive | secret-safe values and metadata | GREEN |
| template | deterministic text transformation | GREEN |
| reconcile | pure observed/desired/plan/change/receipt semantics | GREEN |
| config | ordered in-memory typed resolution with retained provenance; no source I/O/env feature | GREEN; tightened |
| file-store | low-level durable file replacement | GREEN; not an application storage API |
| host | proven file/process contracts + explicit authority only | GREEN; speculative network/secrets removed |
| host-native | file authority enforcement + direct-child lifecycle | GREEN within documented limits |
| events | ordered domain events, bounded retention/cursors, explicit `EventPolicy`; no broker/telemetry | GREEN |
| workflow | deterministic state transition/effects/snapshots; no runtime/I/O | GREEN |
| time | deterministic caller-supplied time/deadline/timer-set semantics | GREEN |
| managed-config | single-writer observe/plan/apply over `FileHost` + reconcile; host failures consistently coded at capability boundary | GREEN; tightened |
| application-edge observation proof | structured `tracing` with execution/correlation/config revision; subscriber outside libraries | GREEN once CI validates current head |

## Integrated composition proof

The application-capabilities proof demonstrates the intended flow without a manager:

```text
ordered raw config layers
    -> ResolvedConfig<...> + ConfigRevision
    -> application-owned policy
        -> EventPolicy

ExecutionContext
    execution_id + correlation_id

application composition
    policy + explicit host facilities + authorities
        -> managed config
        -> event stream
        -> workflow
        -> timer set
        -> owned direct child
```

The application-edge tracing test combines `ExecutionContext` identity and configuration revision into a structured span without changing any semantic capability contract.

## Architecture gates

`scripts/rust-foundation-smoke.sh` is part of this standard. In addition to formatting, strict Clippy, tests, executable proofs and dependency direction, it enforces:

- zero normal dependencies for core and error vocabulary;
- no speculative component/capability/runtime framework vocabulary in core;
- no speculative network/secret host contracts;
- stable error codes are unique;
- raw filesystem/environment access does not enter semantic capability crates;
- Figment environment acquisition is not enabled below composition;
- resolved configuration has no public provenance-discard escape hatch;
- events/workflow/time/managed-config do not depend on config/native host implementations incorrectly;
- semantic crates do not depend on tracing/OpenTelemetry and libraries do not own subscribers;
- the application package contains a real structured tracing proof with canonical execution fields;
- policy composition remains explicit (`ConfigLayers -> typed config -> EventPolicy`);
- application state I/O remains behind host/capability boundaries;
- no custom global telemetry/event/workflow/timer/service manager vocabulary enters the locked layers.

## Deliberately above this standard

The following stay above or after this lock until a concrete consumer proves them:

- Context / AgentWork / canonical gateway execution authority;
- lifecycle and diagnostics models beyond the current typed errors/tracing evidence;
- harness/provider implementations and provider-native sessions;
- network and secret host facilities;
- descendant process-tree containment;
- durable event broker/store;
- workflow scheduler/retry/recovery coordinator;
- multi-writer/CAS managed configuration;
- ordered execution-output contract;
- artifact abstraction;
- OpenTelemetry/exporter configuration and metrics;
- MCP / ACP / A2A / ASA / AGNTCY / Discord / UI projections;
- WIT/Wasm/Bevy runtime choices.

Any change below the lock line must keep this contract green on Ubuntu, macOS and Windows. Higher layers may build on these contracts but must not weaken them implicitly.
