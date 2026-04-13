# planning/domain/

## Purpose
Domain model layer for planning. Defines the types, state machines, and relationship rules for planning items — independent of storage or API concerns.

## Ownership
- Planning item type definitions (Request, Spec, Plan, Task, WorkPackage, Standard)
- Item state definitions and valid state transitions
- Relationship rules (parent-child, dependency, link types)

## Must NOT Own
- File I/O (→ `fs/`)
- API surface or HTTP/MCP concerns (→ `app/`)
- Execution or job launching (→ `execution/`)

## Allowed Dependencies
- `foundation/contracts` — canonical error types and schema validation

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `models.py` | Core planning item type definitions |
| `states.py` | Valid states and transition rules per item type |
| `rels.py` | Relationship definitions and linking rules |
