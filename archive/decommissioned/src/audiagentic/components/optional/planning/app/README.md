# planning/app/

## Purpose
Application layer for the planning domain. Provides the public API surface used by CLI tools, MCP servers, and tests to interact with planning items.

## Ownership
- `PlanningAPI` — the unified entry point for all planning operations
- Configuration loading, path resolution, and ID generation
- Manager modules for claims, indexes, extracts, docs, compaction, validation, and relationships
- Section registry and reference inheritance logic
- Services subdirectory

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
| `planning_app_api.py` | `PlanningAPI` — unified public interface |
| `config.py` | Configuration loading |
| `paths.py` | Path resolution |
| `claims.py` | Claims management |
| `id_gen.py` | ID generation |
| `idx_mgr.py` | Index management |
| `ext_mgr.py` | Extract management |
| `docs_mgr.py` | Documentation management |
| `compact_mgr.py` | Compact management |
| `val_mgr.py` | Validation management |
| `rel_config.py` | Relationship configuration |
| `reference_inheritance.py` | Reference inheritance |
| `section_registry.py` | Section registry |
| `services/` | Services subdirectory |
