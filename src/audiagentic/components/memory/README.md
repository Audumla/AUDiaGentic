# Memory Component

Persistent memory capability for AUDiaGentic agent sessions with swappable backends.

## Architecture

The memory component follows the implementation-cardinality pattern: only one
memory backend is active at a time. Component-level config stores the active
implementation and generic status; implementation-specific config lives in
implementation-scoped state.

### Files

- `memory.yaml` — Component descriptor (config/components/)
- `memory_api.py` — Business logic: implementation selection, config, status
- `memory_mcp.py` — MCP server exposing management tools
- `memory_bootstrap.py` — Post-install initialization

### State

Persisted config lives in the per-component feature state shard:

```
.audiagentic/config/runtime/features/memory.yaml
```

Under `implementations/<impl_id>/options`.

### Ownership Boundary

Memory owns backend state only. Provider adaptation lives in the providers
component — memory does not:
- Enumerate provider IDs
- Write provider file paths
- Branch on provider-specific syntax
- Render provider-specific content

Surface projection flows through the contribution system: memory exports
provider-agnostic content via `build_memory_contributions`, and the providers
component renders it into each provider's instruction/config files.

### v1 Design Decisions

- **No activity server**: v1 ships config projection only. An `ag-memory`
  activity server (retain/recall/reflect) is deferred until the config and
  surface contract is stable.

## Adding a New Memory Implementation

1. Create descriptor at `config/components/memory/<impl>.yaml` with:
   - `type: implementation`, `parent: memory`, `id: <impl>`
   - `options-schema` with implementation-specific config keys

2. Test: verify `memory_select_implementation('<impl>')` works, config persists,
   and provider surfaces update correctly via the contribution system.

3. Provider-specific rendering (if needed) lives in the providers component,
   not in the memory component.
