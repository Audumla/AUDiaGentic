# Rust production foundation standard

Status: **normative** for the production Rust layers below reusable Application Capabilities.

This standard defines a deliberately small dependency floor, pure semantic foundation, host-contract boundary, and native-effect implementation layer. It does not select an application runtime, transport, plugin system, provider model, scheduler, lifecycle framework, diagnostics framework, or service container.

## Locked layering

```text
reusable application capabilities
        |
concrete native effects
  audiagentic-host-native
        |
proven host contracts + authorities
  audiagentic-host
        |
pure foundation semantics
  errors / config / sensitive / template / reconcile
        |
audiagentic-core
```

Dependencies point downward only. Lower layers gain concepts only after a real consumer proves that the concept belongs there.

## 1. Core: identity and opaque composition only

`audiagentic-core` owns only:

- `ApplicationId`;
- `ApplicationInstanceId`;
- `ExecutionId`;
- `CorrelationId`;
- `ApplicationIdentity`;
- `ExecutionContext`;
- opaque `Application<C>` composition.

Core has zero normal dependencies. It does not predeclare capabilities/components, lifecycle, diagnostics, errors, host facilities, runtimes, transports, providers, protocols, schedulers, registries, Wasm engines, ECS frameworks, or async runtimes.

Adding an unrelated application or capability must not require modifying core.

Core's `IdentifierError` is intentionally a zero-dependency construction invariant rather than a coded platform error. When a higher reusable/public boundary exposes such a failure externally, that higher boundary is responsible for projecting it into its own stable coded error contract.

## 2. Pure foundation semantics

Foundation crates perform no filesystem, environment, process, or network discovery/effects. They do not install observability subscribers or depend on an observability backend.

- `audiagentic-errors` — zero-dependency stable boundary error vocabulary: validated `ErrorCode`, prefix-derived `ErrorCategory`, canonical message, resolution, and optional `CodedError` projection.
- `audiagentic-sensitive` — secret-safe values, redaction-safe metadata, and coded validation of reusable metadata keys.
- `audiagentic-template` — deterministic text transformation with coded parse/render failure identity.
- `audiagentic-reconcile` — pure observed/desired/plan/change/receipt semantics with coded identifier validation.
- `audiagentic-config` — typed extraction and ordered resolution of already-acquired in-memory TOML. Every resolution returns `ResolvedConfig<T>` retaining layer identities and deterministic `ConfigRevision` provenance.

There is deliberately **no standalone storage/file-store foundation crate**. Durable filesystem mechanics are native effects and are private implementation details of `audiagentic-host-native` until a real cross-host storage abstraction proves otherwise.

Raw configuration acquisition belongs at an application/effect edge. Application composition translates resolved typed configuration into narrow capability-owned policy values.

## 3. Error standard

Errors remain typed and owned by the crate/domain that understands the failure. A reusable boundary failure exposes stable identity through `audiagentic-errors`:

```text
stable code
category derived from code
canonical message
operator/developer resolution
typed dynamic detail in the domain error
```

Rules:

1. one code identifies one semantic condition;
2. one code has one canonical message;
3. dynamic values are typed fields/details, not alternate canonical messages;
4. error definitions are compiled with the owning crate, so stable identity works before configuration/bootstrap;
5. underlying implementation errors remain in the source chain when appropriate;
6. stable definitions are globally unique below the lock line;
7. transport/protocol envelopes remain later edge projections.

The coded-error contract is currently proven in sensitive, template, reconcile, config, events, workflow, time, and managed-config.

## 4. Host contracts and authority

`audiagentic-host` contains only proven effect contracts and explicit authority values. It performs no native filesystem/process effects and is not a global `HostServices` object or DI container.

**Policy decides desired behaviour. Authority decides which external effects are permitted.**

Current proven host contracts are only:

- filesystem read/write authority + `FileHost`;
- executable launch authority + owned direct-child `ProcessHost`/`ProcessChild` lifecycle.

There are no speculative network, secret, async-host-future, storage-service, or universal host-service contracts. Those are designed only when a concrete consumer proves the required operations and authority model.

## 5. Native effects

`audiagentic-host-native` owns operating-system implementation details behind the host contracts.

### Filesystem

`NativeFileHost` canonicalizes authority roots and target/parent paths, rejects containment escapes and symbolic-link write leaves, and performs durable same-directory temporary-write/fsync/rename behavior through a **private module inside host-native**.

This is portable authority enforcement, not a hostile-filesystem sandbox. Stronger adversarial containment requires platform-specific handle-relative semantics and must not be claimed until implemented.

### Process

`NativeProcessHost` launches only canonicalized executable paths admitted by `ProcessAuthority`, supports explicit stdio/environment behavior, and owns the direct child until wait/kill/drop cleanup.

Process authority is launch authority, not a sandbox. Descendant-tree ownership is deliberately not claimed until Unix process-group/session and Windows Job Object semantics (or equivalent) are implemented and proven by a harness consumer.

## 6. Observability

Observability is a core design concern, not a foundation service.

Operational instrumentation uses Rust `tracing` at meaningful application/runtime/effect boundaries. Pure semantic crates do not depend on tracing/OpenTelemetry and libraries do not install a subscriber.

The current application-edge proof owns `tracing`/`tracing-subscriber` and proves a structured `application.execution` span with:

- `execution_id`;
- `correlation_id`;
- `config_revision`.

OpenTelemetry, JSON/file/console formatting, collectors, sampling, and metrics remain subscriber/exporter choices above the semantic contract. Domain events, stable errors, operational trace events, and externally consumable execution output remain distinct concepts.

## 7. Architecture acceptance gate

`scripts/rust-foundation-smoke.sh` is normative. It must prove on every supported OS:

1. formatting, strict Clippy, workspace tests, and executable composition proofs;
2. zero normal dependencies in core and error vocabulary;
3. explicit downward dependencies for every pure-foundation, host, native-host, and application-capability crate;
4. no filesystem/environment/process/network effects in pure semantic layers;
5. no speculative host/service-container contracts;
6. native filesystem durability exists only inside host-native; no standalone file-store crate or dependency may return;
7. config cannot enable environment acquisition or silently discard resolved provenance;
8. stable coded reusable errors exist and codes are globally unique;
9. public event/workflow monotonic identities reject exhaustion rather than panic or wrap;
10. semantic crates have no telemetry backend dependency and libraries own no tracing subscriber;
11. the application-edge structured tracing proof contains the canonical execution fields;
12. no global capability/service/event/workflow/timer/observability manager vocabulary enters locked layers;
13. all Cargo build/test/run/tree checks use the committed lockfile with `--locked`.

A successful run emits `PURE_FOUNDATION_OK`, `LAYER_CONTRACT_OK`, `APPLICATION_CAPABILITIES_LOCK_OK`, and `RUST_PRODUCTION_FOUNDATION_OK` among the detailed layer markers. GitHub validates the same contract on Ubuntu, macOS, and Windows.

## Relationship to Application Capabilities

The next layer is defined by [`application-capabilities.md`](application-capabilities.md). Events, workflow, deterministic time, and managed configuration belong there; they do not move into core/foundation merely because multiple applications use them.

Context, AgentWork, provider/harness/gateway/protocol work may build above these locked layers but may not weaken them implicitly. Future lifecycle, diagnostics, network/secrets, artifact/storage, scheduler, or runtime concepts are added only where a real consumer proves the boundary.
