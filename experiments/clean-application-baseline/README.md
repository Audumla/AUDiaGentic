# Clean application baseline spike

Decision spike for the minimal AUDiaGentic vocabulary and multi-repo-friendly application model.

Architectural terms under test:

- Runtime
- Application
- Component
- Capability

The spike must prove that a small application can use plain Rust capabilities without Bevy, a larger application can use a Bevy-backed component privately, a runtime-loaded WebAssembly Component can satisfy a WIT capability, and the same application capability can be projected through MCP without protocol/runtime types leaking across boundaries.

## Shape under test

```text
Runtime
  -> Application
       -> Capability API <- native/plain component
                         <- Bevy-backed component
                         <- runtime-loaded Wasm component facade
       -> MCP adapter projects Application capabilities
```

`application` deliberately depends only on `capability-api`. CI fails if its Cargo tree contains Bevy, RMCP, Wasmtime, or wash-runtime. Infrastructure choices stay behind capability implementations/adapters.

The Bevy implementation reuses the previous standalone Bevy runtime spike rather than copying ECS machinery. The Wasm implementation reuses the previous standalone wash-runtime/WIT smoke behind a narrow `ComponentProbe` facade. That first integration boundary is intentionally process-separated; a same-process embedded host is a later gate if this baseline remains clean.

## Pass criteria

1. format, clippy `-D warnings`, and workspace tests pass;
2. minimal application dependency tree contains no Bevy/RMCP/Wasmtime/wash-runtime;
3. previous WIT/wash-runtime component smoke remains green;
4. one composed application invokes a Bevy-backed workflow capability;
5. the same application invokes the runtime-loaded component probe capability;
6. an RMCP server projection can be constructed from `Application` without importing Bevy/wash-runtime;
7. no registry, service locator, plugin manager, or generic DI container is introduced.

This is an architecture experiment only. Do not merge as production architecture.
