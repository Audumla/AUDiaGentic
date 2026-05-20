# planning/app/

## Purpose
Application layer for the planning domain. Provides the public API surface used by CLI tools, MCP servers, and tests to interact with planning items.

## Ownership
- `PlanningAPI` — the unified entry point for all planning operations
- API type definitions (request/response shapes)
- Base manager contracts used by the fs/ layer

## Must NOT Own
- File system read/write (→ `fs/`)
- Domain model types (→ `domain/`)
- MCP tool registration (→ `tools/mcp/audiagentic-planning/`)

## Allowed Dependencies
- `foundation/contracts` — schema validation and error types
- `planning/domain` — domain model types
- `planning/fs` — file system operations

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `api.py` | `PlanningAPI` — unified public interface |
| `api_types.py` | Request and response type definitions |
| `base_mgr.py` | Base manager contract (extended by fs/ managers) |
