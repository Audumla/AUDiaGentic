# planning/fs/

## Purpose
File system layer for planning. Implements all durable read/write operations against `.audiagentic/planning/` and `docs/planning/`.

## Ownership
- Reading and writing planning item markdown files
- Scanning planning directories for items
- Extract JSON index management
- Repository layout for planning artifacts

## Must NOT Own
- Domain model logic (→ `domain/`)
- API surface or public interface (→ `app/`)
- Item state machine transitions (→ `domain/states.py`)

## Allowed Dependencies
- `foundation/contracts` — error types
- `planning/domain` — item types for deserialization

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `repo.py` | High-level planning repository operations |
| `read.py` | Read and parse planning item files |
| `scan.py` | Directory scanning and item discovery |

## Storage layout
```
docs/planning/
  requests/request-XXXX.md
  specifications/spec-XXXX.md
  tasks/core/task-XXXX.md
  plans/plan-XXXX.md
  work-packages/wp-XXXX.md
  standards/standard-XXXX.md

.audiagentic/planning/
  extracts/          ← JSON extract cache
  config/            ← workflow config (planning.yaml, profiles.yaml, etc.)
```
