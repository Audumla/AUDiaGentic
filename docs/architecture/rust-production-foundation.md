# Rust production foundation standard

Status: **normative** for the production Rust layers below reusable Application Capabilities.

This standard defines the dependency floor and host boundary on which the application-capability layer is built. It is intentionally small and does not select a runtime, transport, plugin system, provider model, workflow engine, lifecycle framework, diagnostics framework, or application framework.

## Layering

```text
reusable application capabilities
        |
concrete host implementations
  audiagentic-host-native
        |
proven narrow host contracts + authorities
  audiagentic-host
        |
foundation libraries
  errors / config / sensitive / template / reconcile / file-store
        |
audiagentic-core
```

Dependencies point downward only. A lower layer gains a concept only after a real consumer proves that the concept belongs there.

## Core

`audiagentic-core` owns only proven generic application/execution identity and opaque `Application<C>` composition:

- `ApplicationId`;
- `ApplicationInstanceId`;
- `ExecutionId`;
- `CorrelationId`;
- `ApplicationIdentity`;
- `ExecutionContext`;
- `Application<C>`.

Core has zero normal dependencies and does not define component/capability registries, lifecycle state, diagnostics, errors, host facilities, runtimes, transports, providers, protocols, Wasm engines, ECS frameworks, or async runtimes. Those concepts are introduced in the layer that first proves they are needed.

`Application<C>` treats `C` as opaque application-owned composition. Adding an unrelated capability must not require modifying core.

## Foundation libraries

Foundation crates are small semantic libraries rather than managers.

- `audiagentic-errors` owns stable boundary error identity: validated codes, a machine-readable category derived from the code prefix, canonical messages, resolutions, and the optional `CodedError` projection trait. It has zero normal dependencies and no registry/runtime loader.
- `audiagentic-config` owns typed extraction and ordered resolution of already-acquired in-memory TOML sources. It does not discover files, environment, projects, or global configuration. Every public resolution returns `ResolvedConfig<T>` retaining ordered layer identities and a deterministic `ConfigRevision`; there is no convenience API that silently discards provenance.
- `audiagentic-sensitive` owns secret-safe values and redaction-safe metadata.
- `audiagentic-template` is deterministic text transformation.
- `audiagentic-reconcile` owns pure observed/desired/plan/change/receipt semantics.
- `audiagentic-file-store` owns low-level durable file replacement and is not an application storage API.

Raw configuration acquisition belongs at the application/host edge. Application composition translates resolved typed configuration into narrow capability-owned policy values.

## Error standard

Errors remain owned by the crate/domain that understands the failure. Internal implementation errors may remain ordinary typed Rust errors.

A failure that forms part of a reusable capability/application boundary exposes stable identity through `audiagentic-errors`:

```text
stable code
machine category derived from code
canonical message
operator/developer resolution
```

One code identifies one semantic condition and one canonical message. Dynamic values stay in typed error fields/details. Error definitions are compiled with their owning capability so error identity works before runtime configuration bootstrap. Public transport envelopes remain edge projections.

## Host contracts and authority

`audiagentic-host` contains only host-facility contracts whose semantics are currently proven by consumers. It is not a DI container and does not aggregate facilities into a global service locator.

**Policy decides desired behaviour. Authority decides which external effects are permitted.**

Concrete host implementations enforce authority. Capabilities receive only the host facility and authority they actually require.

### Filesystem

`NativeFileHost` proves contained filesystem access by canonicalizing authority roots and targets/parents, rejecting escapes and symbolic-link write leaves, and routing durable replacement through `audiagentic-file-store`.

This is portable authority enforcement, not a hostile-filesystem sandbox. Stronger adversarial containment would require platform-specific handle-relative semantics and must not be claimed until implemented.

### Process lifecycle

The native process host owns direct-child lifecycle with explicit executable authority and stdio policy. Process authority is launch authority, not a sandbox. Complete descendant-tree ownership is intentionally not claimed until Unix process-group/session and Windows Job Object semantics are proven by a real harness consumer.

### Future facilities

There are currently **no speculative network or secret host contracts** in the locked host layer. When a real provider/application consumer proves those needs, the contracts will be designed from the required operations, authority model, sync/async boundary, and error semantics rather than predeclared generically.

## Observability

Observability is a design concern, not a foundation service.

Operational instrumentation uses the Rust `tracing` ecosystem at meaningful application/runtime/effect boundaries. Foundation and pure semantic capability crates do not install a global subscriber, define a telemetry bus, or depend on OpenTelemetry merely to obtain logs.

Execution/correlation identity comes from core; configuration provenance comes from `ConfigRevision`; stable failures come from coded boundary errors. The application-edge proof owns `tracing`/`tracing-subscriber` and verifies a structured `application.execution` span containing `execution_id`, `correlation_id`, and `config_revision`. Semantic libraries remain independent of that subscriber choice.

OpenTelemetry, JSON logs, rotating files, consoles, remote collectors, sampling, and metrics remain runtime/subscriber/exporter choices. Domain events, operational trace events, stable errors, and externally consumable execution output are distinct concepts and must not be collapsed into one generic event model.

## Architecture gates

`scripts/rust-foundation-smoke.sh` is part of this standard. It must continue to prove:

1. Rust formatting and strict Clippy;
2. the complete Rust workspace test suite;
3. Tiny, Medium, Large and integrated application-capability composition proofs;
4. zero normal dependencies in `audiagentic-core` and `audiagentic-errors`;
5. downward dependency direction through foundation, host and application-capability layers;
6. no Bevy/RMCP/Wasmtime/wash-runtime/Tokio/async-trait leakage into the production foundation;
7. no raw filesystem/environment discovery in semantic configuration/capability crates;
8. configuration cannot enable environment acquisition or discard resolved provenance through a convenience API;
9. no speculative network/secret contracts in the locked host layer;
10. no custom observability/service/event/workflow/timer manager abstractions in the locked layers;
11. stable coded boundary errors and globally unique stable error-code definitions across the locked boundary crates;
12. a real structured tracing proof exists only at the application edge and no library owns a tracing subscriber;
13. application state I/O uses host/capability boundaries rather than bypassing them;
14. all Cargo build/test/run/tree checks use the committed lockfile with `--locked`.

The `rust-production-foundation` workflow executes the contract on Ubuntu, macOS and Windows.

## Relationship to Application Capabilities

The next layer is defined by [`application-capabilities.md`](application-capabilities.md). Events, workflow, deterministic time, managed configuration and their policies belong there; they do not move into core or foundation merely because multiple applications use them.

Higher Context/AgentWork/provider/gateway/protocol/runtime work may build on these layers but may not weaken the foundation contract implicitly. Lifecycle, diagnostics, network/secrets, artifact storage, schedulers and other future concepts are added only where real consumers prove the boundary.
