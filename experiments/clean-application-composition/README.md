# Clean application composition spike

Decision spike for the reduced AUDiaGentic vocabulary and multi-repo application model.

The architecture under test has only four AUDiaGentic-level concepts:

- **Runtime** — native process/runtime substrate; ordinary Rust/Tokio/Wasmtime/RMCP as needed.
- **Application** — the composition root in the consuming app repo.
- **Component** — one implementation/building block, native Rust or WebAssembly Component.
- **Capability** — the semantic contract consumed by application code and surfaces.

There is deliberately no generic AUDiaGentic Plugin, Provider, Bundle, ServiceContribution, service locator, component registry, or DI container in this spike.

## Shape under test

```text
minimal application
  application main (~ordinary Rust composition root)
      -> Greeting capability trait
          -> NativeGreeter component
      -> MCP surface (stdio)

mixed application
  application main
      -> Greeting capability trait
          -> independently compiled WasmGreeter component via WIT/Wasmtime
      -> Workflow capability trait
          -> BevyWorkflow native component
      -> same MCP surface semantics (stdio or Streamable HTTP)
```

The components are allowed to use their natural libraries internally. `BevyWorkflow` uses `bevy_app` + `bevy_ecs`; `WasmGreeter` uses Wasmtime; the MCP surface uses RMCP. None of those raw types appear in the capability contract crate.

## Why the application is the composition root

The spike intentionally does **not** introduce an `ApplicationContainer` or generic `CapabilityRegistry`. Native Rust already has a strong composition mechanism: Cargo dependencies plus constructors and traits. The application repo wires the concrete implementations it chooses. Dynamic/cross-language implementations expose a typed Rust facade over a WIT component and satisfy the same capability trait.

That keeps a later app easy to understand:

```rust
let greeting: Arc<dyn Greeting> = Arc::new(WasmGreeter::load(path)?);
let workflow: Arc<dyn Workflow> = Arc::new(BevyWorkflow::spawn()?);
let surface = MixedMcpServer::new(greeting, workflow);
```

No framework registry is required to understand which implementation wins.

## Gates

`bash scripts/smoke.sh` must prove:

1. strict Rust tests/build succeed on Rust 1.95;
2. an independently compiled `wasm32-wasip2` component satisfies a WIT greeting contract;
3. a native implementation satisfies the same Rust capability contract;
4. the minimal MCP app exposes only the greeting tool and its dependency tree contains neither Bevy nor Wasmtime;
5. the mixed app substitutes the Wasm greeting implementation without changing the MCP semantic tool;
6. the mixed app uses the Bevy workflow implementation without exposing Bevy types to MCP/application contracts;
7. mixed stdio MCP works end to end;
8. mixed Streamable HTTP MCP works end to end using the same composed capabilities;
9. a temporary Cargo project **outside this workspace** consumes the capability + component crates and runs successfully, proving the app does not depend on workspace membership/source inheritance;
10. binary sizes are recorded and the script ends with `CLEAN_COMPOSITION_SPIKE_OK`.

## Decision rule

A green run supports this baseline:

```text
AUDiaGentic vocabulary: Runtime + Application + Component + Capability
native reuse:           ordinary versioned Rust crates
runtime isolation:      WIT / WebAssembly Components
state-heavy internals:  optional Bevy implementation
MCP:                    edge surface over capabilities; stdio/HTTP are transport choices
later app repo:         small composition root + config + its own components
```

A failure caused by needing global registries, framework-managed dependency lookup, Bevy types at boundaries, or transport-specific capability implementations counts against the model rather than being papered over.
