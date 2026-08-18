# AUDiaGentic Bevy runtime foundation spike

Decision experiment for whether Bevy should be part of the Rust/Wasm AUDiaGentic target architecture.

This is **not** a proposal to make Bevy the public plugin ABI. The existing Rust/Wasm spike remains the external-boundary model: WIT/WebAssembly Components for independently distributed capabilities, and native Rust HostPlugins for privileged machine capabilities.

## Validation status

**GREEN.** GitHub Actions run `32124754309` completed successfully on the decision-spike implementation and exercised tests, clippy, release builds, the large Bevy workload, RMCP stdio, and RMCP Streamable HTTP end to end.

Validated toolchain:

- Rust `1.95.0`
- `bevy_app = 0.19.1`
- `bevy_ecs = 0.19.1`
- `rmcp = 3.1.3`

Observed runtime results on the GitHub Ubuntu runner:

```text
BEVY_RUNS=50000
BEVY_COMPLETED=49950
BEVY_CANCELLED=50
BEVY_RETRIED=2939
BEVY_TICKS=19
BEVY_ELAPSED_US=3710
BEVY_RUNTIME_OK

STDIO_TOOLS=2
MCP_stdio_OK
MCP_HTTP_READY=http://127.0.0.1:18080/mcp
HTTP_TOOLS=2
MCP_http_OK

SIMPLE_MCP_BYTES=4399376
BEVY_MCP_STDIO_BYTES=7826944
BEVY_MCP_HTTP_BYTES=10397120
BEVY_MCP_SPIKE_OK
```

The timing is a synthetic in-process ECS state-transition benchmark, not an end-to-end I/O benchmark. It demonstrates that tens of thousands of live state records are not a practical capacity concern for this model.

The binary-size result is deliberately part of the decision: Bevy-backed stdio was about 3.27 MiB larger than the plain RMCP stdio baseline before any size-focused optimization. That makes Bevy valuable for complex stateful applications, but poor as a mandatory dependency for every tiny server.

## Questions this spike answers

1. Does `bevy_app` + `bevy_ecs` materially simplify a complex long-lived runtime without requiring the full rendering/windowing/game stack? **Yes.**
2. Can a Bevy runtime remain privately owned behind a small async handle rather than leaking `World`/ECS concepts into application or transport code? **Yes.**
3. Can one application mix a trivial plain-Rust capability and a complex Bevy-backed capability cleanly? **Yes.**
4. Can the same capability composition be exposed over official MCP stdio and Streamable HTTP transports without changing the runtime? **Yes.**
5. Is a plain MCP server meaningfully smaller/simpler when it does not need Bevy? **Yes.**
6. Does Bevy cope comfortably with tens of thousands of live workflow entities in a deterministic smoke workload? **Yes; 50,000 runs converged in 19 ticks in the smoke.**

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

Only direct dependencies on:

- `bevy_app`
- `bevy_ecs`

No top-level `bevy` dependency and no AUDiaGentic dependency on renderer, window, audio, UI, or asset APIs.

## MCP surface used

Official `rmcp` 3.1.3:

- stdio server/client
- Streamable HTTP server/client
- generated tool routing/schema
- Tokio async runtime

The MCP adapter owns protocol concerns. The Bevy runtime knows nothing about MCP.

## Decision

**Adopt Bevy as an optional internal runtime profile/capability, not as AUDiaGentic core and not as the mandatory base of MCP servers.**

The target split is:

```text
external plugin/capability ABI     WIT / Wasm Components
native host + async I/O            Rust / Tokio / wash-runtime
simple capability                  plain Rust or Wasm; no Bevy required
state-heavy runtime capability     bevy_app + bevy_ecs when useful
MCP surface                        rmcp adapter over selected capabilities
```

For MCP specifically, build an application first and expose selected application capabilities through MCP. A tiny MCP server can be `rmcp + Tokio` only. A complex MCP server can compose workflow, agents, recipes, managed operations, or other plugins and allow only the state-heavy services to use Bevy internally. The same application service can be exposed over stdio or Streamable HTTP without changing its runtime semantics.

WIT/Wasm therefore remains the external extensibility and isolation boundary; Bevy remains an implementation technique behind selected capability seams.

## Smoke gates

`bash scripts/smoke.sh`:

- runs Rust tests;
- builds the whole workspace in release mode;
- executes 50,000 workflow instances through Bevy ECS;
- exercises retry and cancellation paths;
- starts the Bevy-backed MCP server over stdio and calls both simple and complex tools using an RMCP client;
- starts the same server over Streamable HTTP and calls the same tools using an RMCP client;
- builds a plain non-Bevy MCP server as a size/complexity baseline;
- prints binary sizes;
- ends with `BEVY_MCP_SPIKE_OK`.
