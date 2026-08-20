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

## Host rule

`audiagentic-host` contains narrow host-facility contracts and explicit authority scopes. It is not a DI container and does not aggregate facilities into a global service locator. Callers pass the specific facility and authority required by a capability.

The current authority objects carry structural policy only. Platform-specific canonicalization, sandboxing, OS process containment, credential providers, networking implementations, and policy enforcement belong to later host implementation work.

Observability is deliberately not modeled as a generic AUDiaGentic `EventSink` or event bus. Later integrations should use the Rust `tracing` ecosystem and OpenTelemetry projection at the appropriate runtime/application edge.

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
7. host contracts do not depend upward on config, file-store, template, or reconcile;
8. all Cargo build/test/run/tree checks use the committed lockfile with `--locked`.

The `rust-production-foundation` workflow executes this contract on Ubuntu, macOS, and Windows so platform-specific behavior cannot silently escape the foundation gate.

## Deliberately not in this baseline

The following remain later layers and must not be pulled downward to make an early feature easier:

- embedded Wasm runtime and raw Wasmtime vs wash-runtime decision;
- Bevy runtime implementation;
- workflow or recipe semantics;
- managed config/process semantics;
- MCP/RMCP adapters;
- agent/provider-specific behavior;
- generic plugin systems, dependency injection containers, or service locators.

The architecture spikes remain useful regression evidence, but production code is not promoted by renaming spike crates.

## Next production sequence

1. stabilize these core/foundation contracts only as concrete consumers require it;
2. implement platform host facilities behind the narrow contracts;
3. prove one independently distributed component/capability boundary with WIT;
4. compare raw Wasmtime and wash-runtime using that boundary;
5. add the optional Bevy runtime behind a domain capability contract;
6. add workflow/managed-config/managed-process capabilities;
7. project selected application capabilities into MCP at the outer edge.
