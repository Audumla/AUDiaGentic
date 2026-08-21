# Application capabilities architecture standard

Status: **normative** for production Rust from `audiagentic-core` through reusable Application Capabilities. Context, AgentWork, providers, harnesses, gateway, protocols, UI, and distributed-runtime semantics remain above this line.

This contract locks only concepts current code proves. Missing future abstractions are preferable to premature abstractions that later applications must work around.

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
native effect implementations
  host-native: filesystem durability + direct child process
                    |
proven host contracts + authorities
  file / process
                    |
pure foundation semantics
  errors / config / sensitive / template / reconcile
                    |
core
  application identity / execution+correlation identity / Application<C>
```

Dependencies point downward only. Lower layers do not know the application, provider, transport, runtime, UI, or protocol that consumes them.

## 1. Core stays capability-neutral

`audiagentic-core` is zero-dependency and contains only application/execution identity plus opaque `Application<C>` composition. It does not predeclare component/capability IDs, lifecycle state, diagnostics, workflow, configuration, providers, logging, plugins, host facilities, runtime, or service-container semantics.

Adding an unrelated application or capability must not require modifying core.

## 2. Foundation stays pure

`errors`, `sensitive`, `template`, `reconcile`, and `config` are semantic libraries. They perform no native filesystem/environment/process/network effects and have no telemetry backend dependency.

The old standalone `file-store` split is intentionally removed: durable filesystem mechanics are implementation details of `host-native`, not a semantic foundation capability or application storage API.

### Configuration

Raw configuration is a top-level operational concern but is not a capability API:

```text
raw sources acquired at an edge
   -> ordered ConfigLayers
      -> ResolvedConfig<T>
           typed value
           ConfigRevision
           ordered layer identities
         -> application composition
            -> capability-owned typed policy
               -> capability
```

`audiagentic-config` reads neither files nor environment variables, does not enable Figment environment acquisition, and provides no public convenience path that silently discards resolved provenance.

`ConfigRevision` is deterministic provenance for exact ordered configuration inputs; it is not a cryptographic digest.

## 3. Policy and authority are different

**Policy decides desired behaviour. Authority decides which external effects are permitted.**

Current examples:

- `EventPolicy` controls in-memory event retention;
- `ProcessRequest` describes requested child-process behavior;
- `ProcessAuthority` controls which executable paths may be launched;
- `FileReadAuthority` / `FileWriteAuthority` define filesystem scope.

There is no universal `Policy` trait, policy registry, capability registry, service locator, or DI container. A named policy exists only when a real capability has variable behavior worth representing.

## 4. Host contracts are earned by consumers

The host layer currently exposes only file and direct-child process contracts because those are the only native effects current capabilities/proofs require.

There is no speculative `NetworkHost`, `SecretHost`, generic async host future, storage service, or universal `HostServices` container. Future effect contracts are designed from actual consumer operations, authority requirements, error semantics, and concurrency model.

Native OS work lives in `audiagentic-host-native`; the host-contract crate itself performs no native effects.

Process authority is launch authority, not a sandbox. Descendant-tree containment remains future work until Unix process-group/session and Windows Job Object semantics (or equivalent) are implemented and proven.

## 5. Errors are domain-owned and reusable identity is stable

Every Rust error does not become a platform error. Errors remain typed and owned by the crate that understands the failure.

Reusable boundary failures expose `ErrorDefinition` through `CodedError`:

```text
stable code
category derived from code prefix
canonical message
operator/developer resolution
typed dynamic detail
```

Rules:

1. one code identifies one semantic condition;
2. one code has one canonical message;
3. dynamic values remain typed fields/details;
4. categories come from controlled code prefixes (`VAL`, `CON`, `RES`, `IO`, `NET`, `TO`, `EXT`, `CFG`, `VER`, `INT`, `UNS`);
5. definitions are compiled with the owning crate, not loaded from runtime configuration;
6. underlying source errors remain chained when wrapping is appropriate;
7. stable definitions are globally unique below the lock line;
8. protocol error envelopes remain later edge projections.

Coded reusable boundaries currently include sensitive, template, reconcile, configuration, events, workflow, time identifiers, and managed configuration. Managed-config wraps both observe and apply host failures under stable capability-level identity.

Core's zero-dependency identifier construction error is intentionally not a second error framework; higher reusable/edge APIs project it when they expose it externally.

## 6. Application capability responsibilities

### Events

`audiagentic-events` owns typed caller-held domain-event streams, correlation/causation identity, monotonic sequence identity, bounded retention, and cursor paging.

It is not a publisher, broker, subscription registry, retry engine, durable event store, or telemetry system. Event sequence exhaustion returns stable `RES-EVENT-001`; identity never wraps or panics.

### Workflow

`audiagentic-workflow` owns deterministic state transitions, effects-as-data, optimistic revision checking, and application-serializable snapshots.

It performs no I/O, scheduling, retry, persistence, or event publication. Revision exhaustion returns stable `RES-WORKFLOW-001` before domain logic or state mutation; revisions never wrap.

### Time

`audiagentic-time` owns deterministic timestamps, deadlines, timer identity, and caller-driven timer-set semantics. It does not own a clock, sleep, task runtime, or scheduler.

### Managed configuration

`audiagentic-managed-config` composes pure reconciliation with the narrow `FileHost` contract. It owns single-writer observe/plan/apply semantics, not config discovery, parsing, watchers, scheduling, global registration, or a storage abstraction.

## 7. Observability is required but not a platform service

AUDiaGentic does not create an observability manager, telemetry bus, generic `EventSink`, global logger, or proprietary span model.

Operational instrumentation uses Rust `tracing` at meaningful application/runtime/effect boundaries. Semantic crates do not depend on tracing/OpenTelemetry and libraries never install a subscriber.

The application-edge proof owns `tracing` and `tracing-subscriber` and verifies a structured `application.execution` span carrying:

- `execution_id`;
- `correlation_id`;
- `config_revision`.

Nested operational spans/events may later add workflow/effect/process identity and stable `error_code`. Sensitive values must never be trace fields.

OpenTelemetry, collectors, formatting, files, sampling, and metrics remain runtime/subscriber/exporter choices above the semantic contracts.

## 8. Domain events, errors, telemetry, and execution output are distinct

```text
Domain event      application-semantic evidence
Stable error      reusable failure identity + typed detail
Trace event/span  operational diagnostic evidence
Execution output  externally consumable ordered result/progress
```

They may share execution/correlation identity but do not become a universal event model. Ordered execution output remains above this lock until execution authority proves its consumer contract.

## 9. Integrated composition proof

The application-capabilities proof demonstrates the intended composition without a manager:

```text
ordered raw config layers
    -> ResolvedConfig<...> + ConfigRevision
    -> application policy
        -> EventPolicy

ExecutionContext
    execution_id + correlation_id

Application<C>
    typed policy + explicit host facilities + authorities
        -> managed config
        -> event stream
        -> workflow
        -> caller-driven timers
        -> owned direct child
```

The application-edge tracing test combines execution identity and configuration provenance without changing any semantic capability contract.

## 10. Mechanical lock rules

`scripts/rust-foundation-smoke.sh` is part of this architecture. It enforces:

- explicit dependency direction for every locked crate;
- effect-free pure foundation and semantic capability code;
- no standalone file-store/storage layer;
- no speculative host facilities or service containers;
- stable coded reusable errors with globally unique codes;
- checked event/workflow monotonic identity exhaustion;
- config provenance and config-to-policy composition;
- no telemetry backend in semantic crates and no library subscriber ownership;
- a real structured application-edge tracing proof;
- no global event/workflow/timer/capability/service/observability managers;
- strict committed lockfile use;
- full format/Clippy/test/example validation.

Successful acceptance emits `PURE_FOUNDATION_OK`, `LAYER_CONTRACT_OK`, `APPLICATION_CAPABILITIES_LOCK_OK`, and `RUST_PRODUCTION_FOUNDATION_OK` and must pass on Ubuntu, macOS, and Windows.

## Deliberately above this lock

The following remain above or after this standard until a concrete consumer proves them:

- Context / AgentWork / canonical gateway execution authority;
- additional lifecycle/diagnostics models;
- harness/provider implementations and provider-native sessions;
- network and secret host facilities;
- descendant process-tree containment;
- durable event broker/store;
- workflow scheduler/retry/recovery coordinator;
- multi-writer/CAS managed configuration;
- ordered execution-output contract;
- artifact/storage abstraction;
- OpenTelemetry exporter configuration and metrics;
- MCP / ACP / A2A / ASA / AGNTCY / Discord / UI projections;
- WIT/Wasm/Bevy runtime choices.

Any change below this line must preserve the mechanical layer contract. Higher layers may build on these abstractions but may not weaken them implicitly.
