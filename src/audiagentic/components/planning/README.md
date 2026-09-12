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
docs/planning/
  active/
    <plan-name>/
      <ID>.md       ← pending items
  completed/
    <plan-name>/
      <ID>.md       ← completed items
  TEMPLATE_ITEM.md
```

Reviews live alongside plan items:

```
docs/planning/
  active/<plan>/reviews/<ITEM-ID>/RV##.md
  completed/<plan>/reviews/<ITEM-ID>/RV##.md
```

New reviews may be created for active items. Completed items cannot receive or
reopen an active review; create a new planning item when post-completion work
needs independent review. A newly created review starts in `active/` with
review state `created`; moving the review itself to `closed` archives it under
`completed/`.

Each item has YAML frontmatter (`id`, `order`, `plan`, `state`, `priority`, `work`)
and standard markdown sections: Description, Steps, Files, Validation, Acceptance
Criteria, Effort & Risk, Standards, and Notes.

## States

| State | Folder | Meaning |
|---|---|---|
| `pending` | `active/` | Work not yet started |
| `in_progress` | `active/` | Active implementation |
| `completed` | `completed/` | Work finished |
| `superseded` | `completed/` | Replaced by another item |
| `deprecated` | `completed/` | Outdated but retained for reference |

States and transitions are defined in `workflows.yaml`; the Python code reads them at runtime.

## Review lifecycle

| Review state | Folder | Meaning |
|---|---|---|
| `created` | `active/` | New finding or feedback to consider |
| `considered` | `active/` | Triaged / incorporated but still open |
| `closed` | `completed/` | Review handled and archived |

Reviews target active items. This keeps the completed-item invariant truthful:
completed items retain evidence and have no active reviews.

An item cannot be completed while a linked review is still `created` or
`considered`; resolve and close those reviews first.

The workflow contract is authoritative in `workflows.yaml`: items start in
`pending`, may move between the listed item states only through its declared
transitions, and reviews start in `created` and follow the declared
`created`/`considered`/`closed` transitions. The placement map, not a state-name
special case, selects `active/` versus `completed/`.
Items start in `pending`; reviews start in `created`.

Each newly created review is recorded in the parent's `Reviews` section. That
link is part of the local repository integrity contract: review mutations fail
closed when the review, parent, plan, or backlink disagree. Planning writes use
a local roll-forward journal under `.audiagentic/runtime/planning/`; a later
planning API use reconciles prepared moves before serving the request. Planning
events and ledger-to-plan projections use durable outboxes with at-least-once
delivery; consumers must be idempotent.

## Implementations

Declared in `config/components/planning/`. The `planning-local-docs` implementation stores
items as markdown files in the project tree. The current runtime contract is local Markdown;
hosted backends require a separate implementation adapter before they can be selected.
