# Rust production foundation baseline

This is the production Rust layering baseline. It starts from `main` rather than from an architecture spike and intentionally contains no inherited runtime, transport, component-engine, or workflow assumptions.

## Locked vocabulary

- **Runtime** — execution machinery chosen by an application or capability implementation.
- **Application** — identity plus an application-defined strongly typed composition.
- **Component** — an independently distributable implementation unit when a component boundary is actually needed.
- **Capability** — a semantic contract owned by its domain. There is no universal capability base trait or registry.

## Layering

```text
application-specific code
        |
        +---------------- optional domain capability crates
        |
        +---- concrete host implementations
        |       audiagentic-host-native
        |              |
        |              +---- audiagentic-host contracts
        |              +---- selected foundation libraries
        |
        +---- foundation libraries
        |       sensitive
        |       template
        |       reconcile
        |       config
        |       file-store
        |
        +---- narrow host-facility contracts
        |       filesystem / process / network / secrets
        |
        +---- audiagentic-core
                identity
                Application<C>
                execution/correlation identity
                generic lifecycle
                diagnostics projection
```

`audiagentic-core` has zero normal dependencies and does not know any concrete capability, host facility, runtime, transport, protocol, Wasm engine, ECS, or async framework.

## Composition rule

`Application<C>` treats `C` as opaque. `C` is defined by each application. Adding an unrelated capability must not require modifying `audiagentic-core`.

This intentionally rejects both a universal service registry and a central `Application<CapabilityA, CapabilityB, ...>` whose generic slots grow whenever the platform learns a new capability.

Type erasure is a local boundary choice, not an application-wide architectural primitive.

## Foundation library rule

Foundation libraries are small semantic libraries, not managers:

- `audiagentic-sensitive` owns secret/redaction-safe primitives.
- `audiagentic-template` is pure deterministic text templating.
- `audiagentic-reconcile` owns observed/desired/plan/change/receipt vocabulary and pure planning helpers.
- `audiagentic-config` extracts application-owned typed Rust configuration through Serde + Figment and requires Schemars-compatible models.
- `audiagentic-file-store` owns small durable file operations and deliberately does not own configuration schemas.

`audiagentic-file-store::write_atomic` performs same-directory temporary writes, flushes file contents before replacement, preserves unrelated temporary-name collisions, and relies on `std::fs::rename` replacement semantics that are exercised on Unix and Windows by the same overwrite test.

## Host rule

`audiagentic-host` contains narrow host-facility contracts and explicit authority scopes. It is not a DI container and does not aggregate facilities into a global service locator. Callers pass the specific facility and authority required by a capability.

The authority objects carry structural policy only. Enforcement belongs to concrete host implementations.

Filesystem access is synchronous at the host contract boundary. The first concrete native implementation uses blocking operating-system filesystem operations; runtimes that require offloading may adapt this at their runtime edge. This avoids making Tokio or another async framework part of the foundation contract and maps cleanly to a future WIT filesystem boundary.

`audiagentic-host-native::NativeFileHost` is the first concrete host proof. It:

- canonicalizes the granted root;
- canonicalizes read targets and rejects targets outside the root;
- canonicalizes write parents and writes through the canonical parent path;
- rejects directory-symlink escapes;
- rejects writes directly to a symbolic-link leaf;
- requires the authority root and write parent to already exist;
- uses `audiagentic-file-store` for durable replacement.

This is authority enforcement, not a claim of a hostile-filesystem sandbox. Path-based preflight still has a time-of-check/time-of-use window if another actor can concurrently replace directories. Strong adversarial containment, if required, belongs in later platform-specific handle-relative/openat-style implementations rather than being falsely promised by this portable proof.

Observability is deliberately not modeled as a generic AUDiaGentic `EventSink` or event bus. Operational telemetry should use the Rust `tracing` ecosystem and OpenTelemetry projection at the appropriate runtime/application edge. Domain events remain domain-owned and may later be routed through local, MQTT, NATS, durable-stream, or other adapters without changing `audiagentic-core`.

## Errors

Each domain/foundation crate owns its own typed errors. Core's `Diagnostic` is a projection type for machine-readable boundary diagnostics; it is explicitly not the base error type that every capability must return.

Human presentation remains separate from machine identity.

## Architecture gates

`scripts/rust-foundation-smoke.sh` is part of the architecture contract. It verifies:

1. formatting and strict Clippy;
2. the entire Rust workspace test suite;
3. executable Tiny, Medium, and Large applications using the same `Application<C>` shape;
4. zero normal dependencies in `audiagentic-core`;
5. no Bevy/RMCP/Wasmtime/wash-runtime/Tokio/async-trait dependency in either the resolved production dependency graph or production manifests;
6. no rejected spike/framework vocabulary (`Workflow`, `ComponentProbe`, `DynApplication`, `NoWorkflow`, `NoComponentProbe`, or universal `CapabilityError`) in core;
7. host contracts do not depend upward on config, file-store, template, reconcile, or native host implementations;
8. the native filesystem host depends only on the host contract, file-store, and local error support rather than application/core/config/template/reconcile layers;
9. Large has no direct file-store dependency or import, so its state I/O must traverse `FileHost`;
10. all Cargo build/test/run/tree checks use the committed lockfile with `--locked`.

The `rust-production-foundation` workflow executes this contract on Ubuntu, macOS, and Windows so platform-specific behavior cannot silently escape the foundation gate.

## Deliberately not in this baseline

The following remain later layers and must not be pulled downward to make an early feature easier:

- embedded Wasm runtime and raw Wasmtime vs wash-runtime decision;
- Bevy runtime implementation;
- workflow or recipe semantics;
- managed config/process semantics;
- MCP/RMCP adapters;
- agent/provider-specific behavior;
- generic event buses or queue abstractions before a domain proves its required delivery semantics;
- generic plugin systems, dependency injection containers, or service locators.

The architecture spikes remain useful regression evidence, but production code is not promoted by renaming spike crates.

## Next production sequence

1. keep the core/foundation contracts stable unless a concrete consumer proves a change is needed;
2. use the native filesystem host proof as the pattern for the next concrete host facility;
3. implement native process execution/lifecycle against a real managed-process or harness consumer, including explicit authority and cleanup semantics;
4. prove one real domain capability using those host boundaries without a global runtime container;
5. define the first independently distributed component/capability boundary with WIT;
6. compare raw Wasmtime and wash-runtime using that actual boundary;
7. add the optional Bevy runtime behind a domain capability contract;
8. add reusable workflow/managed-config/managed-process capabilities only where the real application requires them;
9. project selected application capabilities into MCP at the outer edge.
