# AUDiaGentic Rust/Wasm foundation spike

This is a greenfield target-architecture experiment. It is intentionally **not** a port of the Python foundation.

## Architectural mapping

| Concern | Rust/Wasm target |
|---|---|
| Cross-capability contract | WIT package/interface |
| Required capability | component WIT import |
| Provided capability | component WIT export or native HostPlugin |
| Application composition | wash-runtime `Workload` |
| Pure/replayable application logic | Wasm component |
| Long-lived workload state | workload `Service` (not used in first smoke) |
| Privileged/native machine integration | Rust `HostPlugin` |
| Durable state | explicit storage capability |
| Runtime permissions | `LocalResources` / supplied host interfaces |
| Lifecycle | workload + HostPlugin lifecycle |
| Async runtime | Tokio + Wasmtime/wash-runtime |
| Internal native dependencies | ordinary Rust ownership/traits, not a global DI container |

## Explicitly not migrated

The target has no equivalent of the Python `ComponentDescriptor`, component registry, feature registry, `ServiceContribution`, Pluggy manager, Dishka provider graph, generic `ProjectService`, generic `SessionService`, or runtime service locator.

If semantics from those areas survive, they must become a WIT contract, component, workload service, native host plugin, durable store, or plain host bootstrap policy.

## Spike graph

```text
native Rust audiagentic host
  |
  +-- AuditHostPlugin
  |     provides audiagentic:host/audit@0.1.0
  |
  +-- workload
        |
        +-- process.wasm
        |     imports audiagentic:workflow/engine@0.1.0
        |     imports audiagentic:host/audit@0.1.0
        |     exports wasi:http/incoming-handler@0.2.2
        |
        +-- workflow-default.wasm OR workflow-alt.wasm
              exports audiagentic:workflow/engine@0.1.0
```

HTTP is only a deterministic smoke trigger. It is not part of the proposed foundation API.

## Acceptance gates

1. Native Rust host starts with no workflow/agent/recipe semantics compiled into it.
2. `process.wasm` binds to a separate workflow provider solely by WIT import/export.
3. An alternative workflow provider can replace the default without changing the consumer.
4. Missing workflow capability fails workload resolution before execution.
5. Duplicate workflow providers are rejected explicitly; never silently selected by registration order.
6. Native Rust `AuditHostPlugin` is bound only because the component imports its WIT interface.
7. Audit plugin receives workload bind/resolved/unbind lifecycle callbacks.
8. Components receive no outbound network/DNS/host-loopback permissions and no volume mounts.
9. Workload and host stop cleanly.
10. The core host contains no agent, workflow, recipe, MCP, source-control, or developer-app semantics.
