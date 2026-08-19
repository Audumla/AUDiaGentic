# Rust Baseline v2

This spike freezes the minimal AUDiaGentic application seam and adds only the foundational layers already justified by existing semantics.

## Architectural vocabulary

Only four AUDiaGentic-wide terms are required:

- **Runtime** — constructs and runs an application.
- **Application** — a composition of selected capability implementations and edge adapters.
- **Component** — an independently usable implementation/building block, native or WebAssembly.
- **Capability** — a stable semantic contract implemented by a component.

Technology-specific terms stay technology-specific: Rust crate, WIT interface, Wasm component, Bevy Plugin, MCP transport, Cargo dependency.

## Dependency bands

```text
edge adapters / concrete runtime implementations
                 |
                 v
            Application
                 |
                 v
          Capability APIs
                 |
                 v
               Core

optional foundation libraries are consumed by implementations that need them;
they are not dependencies of Application by default.
```

### Locked core

`audiagentic-core-spike` contains only:

- typed application/component/capability/correlation identity;
- immutable application/execution context;
- generic diagnostic shape and severity;
- component capability metadata/requirements.

It must not depend on Tokio, Bevy, RMCP, Wasmtime, wash-runtime, filesystem/process APIs, workflow, recipes, or application-specific models.

### Application

`audiagentic-application-spike` owns composition-facing handles to explicitly selected capability APIs and the immutable application context. It is not a registry or service locator. Baseline v2 deliberately keeps explicit typed fields for the capabilities under test.

### Capability APIs

Capability contracts own their request/result and typed machine failure semantics. Human-facing diagnostics are a separate core concept. A capability implementation may use Bevy, Wasm, a remote service, or plain Rust without changing its consumer contract.

### Optional foundation leaves

- `sensitive`: structural secret handling and explicit redaction.
- `template`: strict pure scalar template rendering.
- `reconcile`: ownership-aware desired/observed planning that preserves user-owned state.
- `config`: format-neutral ordered config layering with per-path provenance.

These are libraries, not runtime capabilities. They must remain independently optional.

## Explicitly outside core

- Bevy/ECS runtime state;
- Tokio runtime and I/O;
- Wasmtime/wash-runtime component hosting;
- MCP/RMCP, CLI, HTTP, ACP, A2A and other edge adapters;
- workflow, recipes, agents, managed config/process and other application capabilities;
- filesystem/process/network/secrets authority;
- config file formats and config file locations;
- observability exporters.

## Lock-down gates

CI must fail if:

1. core gains Tokio/Bevy/RMCP/Wasmtime/wash-runtime;
2. Application gains Bevy/RMCP/Wasmtime/wash-runtime;
3. pure foundation leaves gain runtime infrastructure;
4. format/clippy/tests fail;
5. existing Bevy, WIT/Wasm, or MCP integration stops composing through the application seam.

## Next layering

The next production-oriented layer should add host authority and reusable capabilities *above* this baseline, rather than widening core:

1. host filesystem/process/secrets/config/observability boundaries;
2. managed-config built from reconcile + host filesystem;
3. recipe effects/receipts built from reconcile semantics;
4. workflow API/implementations (simple/Bevy) separated from the baseline experiment;
5. runtime-loaded WIT components through an embedded component host;
6. MCP and other projections over selected application capabilities.

No generic plugin manager, service locator, DI container, global event bus, or universal registry is part of this baseline.
