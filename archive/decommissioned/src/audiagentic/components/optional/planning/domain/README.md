# planning/domain/

## Purpose

Generic in-memory representation of planning items. Independent of storage or API concerns.

The engine is config-driven — kinds, states, and reference rules are defined in
`.audiagentic/planning/config/` and interpreted by `app/`. This module holds only the
neutral container type carried between layers.

## Ownership

- Generic `Item` dataclass: kind, path, frontmatter dict, body string

## Must NOT Own

- Kind-specific type definitions (kinds are config, not Python types)
- State machine definitions (live in `workflows.yaml`)
- Relationship rules (live in `profiles.yaml` / `planning.yaml`)
- File I/O (→ `fs/`)
- API surface or MCP concerns (→ `app/`)

## Key Modules

| Module      | Responsibility            |
| ----------- | ------------------------- |
| `models.py` | Generic `Item` dataclass  |
