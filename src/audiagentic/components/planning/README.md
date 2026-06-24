# components/planning/

Plan item management for tracking multi-step implementation work across sessions.

## Purpose

Provides MCP tools for creating, listing, updating, transitioning, and deleting plan items.
Items are markdown documents with YAML frontmatter and structured body sections.

## Owns

- Plan item CRUD and state transitions
- Markdown serialization/deserialization for plan items
- MCP tool interface for plan operations

## Must not own

- Plan item rendering or display (provider/surface concern)
- Job orchestration or agent scheduling
- Source control operations

## Key modules

- **planning_api.py**: Pure logic — parse, render, create, list, get, update, transition, delete
- **planning_mcp.py**: MCP server exposing the `ag-planning` tool surface

## Item structure

```
docs/planning/plans/
  active/
    <plan-name>/
      <ID>.md       ← pending items
  completed/
    <plan-name>/
      <ID>.md       ← completed items
  TEMPLATE_ITEM.md
```

Each item has YAML frontmatter (`id`, `order`, `plan`, `state`, `priority`, `complexity`)
and standard markdown sections: Description, Steps, Files, Validation, Effort & Risk, Notes.

## States

| State | Folder | Meaning |
|---|---|---|
| `pending` | `active/` | Work not yet done |
| `completed` | `completed/` | Work finished |

`not_done` is accepted as a read alias for `pending` (legacy items).

## Implementations

Declared in `config/components/planning/`. The `local-docs` implementation stores items
as markdown files in the project tree. Future implementations may back the same MCP interface
with a hosted issue tracker (Jira, Linear, GitHub Projects).
