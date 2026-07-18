# foundation/

Shared low-level primitives used by every higher layer.

## Purpose

Foundation is where AUDiaGentic keeps reusable building blocks that should stay stable across components and runtime implementations.

## Owns

- `components/` component descriptor models, registries, and dependency workflows
- `contracts/` schemas, canonical IDs, errors, and validation helpers
- `event/` generic envelopes, event bus, persistence, and replay
- `logging/` layered logging config, context propagation, and audit-log helpers
- `mcp/` shared MCP server scaffolding and output bridging
- `system/` process and host-level helpers
- `toolchains/` external dependency detection and recipe loading
- `workflow/` state-machine, transition, and propagation primitives

## Must Not Own

- provider-specific adapters
- project install state
- release lifecycle business logic
- user-facing component orchestration

If code needs project-specific state or external service behavior, it usually belongs above this layer.
