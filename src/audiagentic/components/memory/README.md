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
- `hindsight/INSTALL_MAP.md` — Current provider-to-Hindsight installation routes

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

Backend-specific provider integration is contained under the active memory
implementation (for Hindsight: `memory/hindsight/`) and uses generic provider
seams. Memory core returns neutral refresh hints when backend config changes; it
does not render provider files or call provider services directly.

### v1 Design Decisions

- **No activity server**: v1 stores backend config only. An `ag-memory`
  activity server (retain/recall/reflect) is deferred until the memory/provider
  recipe contract is stable.

## Adding a New Memory Implementation

1. Create descriptor at `config/components/memory/<impl>.yaml` with:
   - `type: implementation`, `parent: memory`, `id: <impl>`
   - `options-schema` with implementation-specific config keys

2. Test: verify `memory_select_implementation('<impl>')` works, config persists,
   and provider recipe refresh hints are returned.

3. Backend-specific provider recipes (if needed) live under the implementation
   package, not memory core and not provider core.
