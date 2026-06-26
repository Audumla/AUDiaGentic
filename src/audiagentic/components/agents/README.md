# Agents Component

Agent profile management — bind a provider to a specific model with optional
execution parameters. Profiles are stored per-project in
`.audiagentic/config/agent-profiles.yaml` and resolved at job launch time.

## Architecture

- `models.py` — AgentProfile dataclass, AgentProfilesStore, validation
- `agents_paths.py` — Path resolution for profile config files
- `agents_api.py` — Pure-logic CRUD API (load, save, list, get, create, update, delete, resolve)
- `agents_manage_mcp.py` — Management MCP server (CRUD tools, CLI-side only)
- `agents_mcp.py` — Operational MCP server (resolve tools, provider-facing)

## Two-server pattern

Management (`ag-agents-mgmt`, propagate: `audiagentic`) handles admin operations.
Operational (`ag-agents`, propagate: `audiagentic,providers`) provides resolution
capabilities to providers during job execution.

## Error codes

- `VAL-AGP-001` through `VAL-AGP-005` — Profile validation failures
- `RES-AGP-001` — Profile not found
- `RES-AGP-002` — Duplicate profile ID
- `RES-AGP-003` — No default profile
- `IO-AGP-001` — Failed to read profiles file
- `IO-AGP-002` — Failed to write profiles file
