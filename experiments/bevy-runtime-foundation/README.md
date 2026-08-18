# AUDiaGentic Bevy runtime foundation spike

Decision experiment for whether Bevy should be part of the Rust/Wasm AUDiaGentic target architecture.

This is **not** a proposal to make Bevy the public plugin ABI. The existing Rust/Wasm spike remains the external-boundary model: WIT/WebAssembly Components for independently distributed capabilities, and native Rust HostPlugins for privileged machine capabilities.

## Questions this spike answers

1. Does `bevy_app` + `bevy_ecs` materially simplify a complex long-lived runtime without pulling graphics/windowing/game-engine features?
2. Can a Bevy runtime remain privately owned behind a small async handle rather than leaking `World`/ECS concepts into application or transport code?
3. Can one application mix a trivial plain-Rust capability and a complex Bevy-backed capability cleanly?
4. Can the same capability composition be exposed over official MCP stdio and Streamable HTTP transports without changing the runtime?
5. Is a plain MCP server meaningfully smaller/simpler when it does not need Bevy?
6. Does Bevy cope comfortably with tens of thousands of live workflow entities in a deterministic smoke workload?

## Shape

```text
MCP stdio ─────┐
               │
MCP HTTP ──────┼── AudiagenticMcpServer
               │       ├── add()                 plain Rust
               │       └── workflow_batch()      async handle
               │                                  │
               │                         dedicated runtime thread
               │                                  │
               │                           Bevy App / World
               │                           ├── WorkflowPlugin
               │                           └── MetricsPlugin
               │
               └── rmcp transport only
```

The Bevy `App` is single-owner on its own native thread. Async callers communicate through a bounded Tokio channel and one-shot responses. There is deliberately no `Arc<Mutex<App>>`, service locator, generic registry, or MCP-specific state inside the ECS runtime.

## Bevy surface used

Only:

- `bevy_app`
- `bevy_ecs`

No renderer, windowing, audio, assets, UI, or full `bevy` dependency.

## MCP surface used

Official `rmcp` 3.0.1:

- stdio server/client
- Streamable HTTP server/client
- generated tool routing/schema
- Tokio async runtime

The MCP adapter owns protocol concerns. The Bevy runtime knows nothing about MCP.

## Smoke gates

`bash scripts/smoke.sh` must:

- run Rust tests;
- build the whole workspace in release mode;
- execute 50,000 workflow instances through Bevy ECS;
- exercise retry and cancellation paths;
- start the Bevy-backed MCP server over stdio and call both simple and complex tools using an RMCP client;
- start the same server over Streamable HTTP and call the same tools using an RMCP client;
- build a plain non-Bevy MCP server as a size/complexity baseline;
- print binary sizes;
- end with `BEVY_MCP_SPIKE_OK`.

## Decision rule

A green spike does **not** mean every AUDiaGentic application should use Bevy.

The intended interpretation is:

- WIT/Wasm remains the external plugin/capability boundary.
- Tokio remains the native async I/O runtime.
- `rmcp` remains the MCP protocol/transport implementation.
- Bevy is adopted only where a selected application capability benefits from ECS/schedules/reactive state.
- Simple applications and simple MCP servers must be able to omit Bevy entirely.
