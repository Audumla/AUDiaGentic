# audiagentic-planning MCP

Planning MCP server for AUDiaGentic. Single entry point for all MCP clients — 13 tools.

## Install

```bash
pip install mcp pydantic
```

## Server

```bash
python tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py
```

## Environment Variables

- `AUDIAGENTIC_ROOT`: (optional) Explicit project root path. If set, must contain `.audiagentic/` directory.

## Generic MCP config

```json
{
  "mcpServers": {
    "audiagentic-planning": {
      "command": "python",
      "args": ["tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py"]
    }
  }
}
```

With explicit root:

```json
{
  "mcpServers": {
    "audiagentic-planning": {
      "command": "python",
      "args": ["tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py"],
      "env": {
        "AUDIAGENTIC_ROOT": "/path/to/project"
      }
    }
  }
}
```

## Agent guidance

### Edit first

**Use `tm_edit` for all mutations.** It accepts a list of operations executed atomically — state, label, summary, section writes, content, nested `meta.*`, and top-level frontmatter field updates in one call. Prefer one `tm_edit` over multiple separate calls.

```json
{
  "id": "task-0123",
  "operations": [
    {"op": "state", "value": "done"},
    {"op": "section", "name": "Notes", "content": "Implementation complete.", "mode": "set"}
  ]
}
```

**Supported operations:**
- `state`: `{"op": "state", "value": "done"}`
- `label`: `{"op": "label", "value": "New label"}`
- `summary`: `{"op": "summary", "value": "New summary"}`
- `section`: `{"op": "section", "name": "Notes", "content": "...", "mode": "set"|"append"}`
- `content`: `{"op": "content", "value": "...", "mode": "replace"|"append"}`
- `meta`: `{"op": "meta", "field": "tags", "value": "..."}`
- `field`: `{"op": "field", "field": "spec_refs", "mode": "add"|"remove"|"replace"|"set", "value": "spec-123"}`

**When to use which:**
- Use `field` for top-level frontmatter like `spec_ref`, `spec_refs`, `request_refs`, `task_refs`, `work_package_refs`, `standard_refs`, `plan_ref`
- Use `meta` only for nested `meta.*` values

Examples:
- Remove stale ref: `{"op": "field", "field": "spec_refs", "mode": "remove", "value": "spec-12"}`
- Add plan WP link: `{"op": "field", "field": "work_package_refs", "mode": "add", "value": {"ref": "wp-15", "seq": 1000}}`
- Replace list fully: `{"op": "field", "field": "task_refs", "mode": "replace", "value": [{"ref": "task-251"}]}`

Operations are validated by Pydantic schema — invalid operations return structured errors with suggestions.

### Read cost ladder

```text
tm_get depth=head < depth=meta < depth=full < depth=body
```

- `head` — index-only, no file parse. Use for existence/state checks.
- `meta` — frontmatter only. Use when metadata fields are needed.
- `full` — metadata + body (default). Use for full context.
- `body` — raw markdown only. Use only when the body text is needed.

### Work queue

`tm_list mode=next` returns unclaimed items in a given state — the agent work queue.

### Multi-Agent Coordination

**Multiple agents can work on the same repository using claims.** The planning system provides `tm_claim` for coordinating access to items:

1. **Claim items before work**: `tm_claim op=claim kind=task id=task-0123 holder=agent-name`
2. **Check available work**: `tm_list mode=next` returns unclaimed ready items
3. **View active claims**: `tm_claim op=list` shows all claimed items
4. **Release when done**: `tm_claim op=unclaim id=task-0123`
5. **Set TTL for auto-release**: `tm_claim op=claim ... ttl=3600` (seconds)

**Example workflow:**
```json
// Agent claims a task
{op: "claim", kind: "task", id: "task-0123", holder: "agent-1", ttl: 7200}

// Agent does work
{op: "state", value: "in_progress"}
{op: "section", name: "Progress", content: "...", mode: "append"}

// Agent completes and releases
{op: "state", value: "done"}
{op: "unclaim", id: "task-0123"}
```

**Notes:**
- Claims prevent other agents from picking up the same item via `tm_list mode=next`
- Claims expire after TTL (if set) to prevent stale locks
- Manual state changes work regardless of claims (claims are advisory for work queue)

### Error handling

All errors include a `suggestion` field to help agents recover:

```json
{
  "error": {
    "message": "Invalid operation 'update_state'",
    "suggestion": "Supported operations: state, label, summary, section, content, meta, field"
  }
}
```

Common error patterns:
- Invalid operation → check suggestion for valid ops
- Item not found → use `tm_list` to find valid IDs
- Unknown kind/depth/mode → check suggestion for valid values

## Tools

### `tm_edit(id, operations)` — mutate

Execute one or more operations on a planning item atomically. Use `field` ops for top-level frontmatter add/remove/replace/set and `meta` ops for nested `meta.*`.

**Returns:** `{"id": "...", "operations_executed": N, "result": {...}}`

### `tm_create(kind, label, summary, ...)` — create

Create a planning item. `kind`: `request|spec|plan|task|wp|standard`.
Provide `content` for initial markdown body.
Kind requirements: spec needs `request_refs`; task needs `spec`; wp needs `plan`.
Request extras: `profile`, `source`, `context`, `current_understanding`, `open_questions`.

### `tm_get(id, depth, with_related)` — read

Read a planning item. `depth`: `head|meta|full|body` (default: `full`).

### `tm_list(kind, state, domain, mode, ...)` — query

Query items. `mode`: `list` (default) | `count` (kind×state summary) | `next` (unclaimed ready items).
`kind`, `state`, `domain` are optional filters.

### `tm_section(id, op, section, content)` — section read/write

Read or write a named section. `op`: `get|set|append|get_sub`.
`set` and `append` require `content`. `get_sub` accepts dot-notation paths (`Requirements.Functional`).

### `tm_move(id, domain)` — move

Move a task or wp to a different domain (e.g. `core → provider`).

### `tm_delete(id, hard, reason)` — delete

Delete an item. `hard=False` (default) soft-deletes; `hard=True` removes the file.

### `tm_relink(src, field, dst, seq, display)` — add or set references

Convenience helper for adding or setting references. Prefer `tm_edit` with `field` ops when you need to remove stale refs, replace a whole ref list, or batch reference surgery with other mutations.

### `tm_group(parent, items, label, summary, domain)` — group items

Group configured child items into a configured workflow action target.

### `tm_refs(id, field, with_related)` — configured reference lookup

- Omit `id` → list configured default-reference collection for `field`.
- `id=<reference-item>` → get that item with body.
- `id=<other-item>` → list effective refs for that item and field.

### `tm_claim(op, id, kind, holder, ttl)` — ownership claims

`op`: `claim` (requires `kind`, `id`, `holder`; optional `ttl` seconds) | `unclaim` (requires `id`) | `list` (optional `kind` filter).

### `tm_docs(op, id, kind, profile_pack, role)` — documentation resources

`op`: `surfaces` | `surface` (id=surface_id) | `refs` | `profiles` | `profile` (id=profile_id) | `support` (optional id, role) | `sync_req` (requires kind) | `pending` (requires kind).

### `tm_admin(op, id, tail)` — admin and maintenance

`op`: `validate` | `index` | `reconcile` | `events` (optional `tail`, default 20) | `verify` | `check_sensitive` (requires `id`).

## Guidance

- **Do use these tools for:** Planning-domain CRUD, state changes, validation, queries, doc editing, and governance
- **Don't use this server for:** Provider execution, prompt launching, runtime job control, general code edits, or agent job submission
- **Multi-agent:** Use claims for coordination; tm_list mode=next automatically skips claimed items
- **Errors:** All errors include suggestions for agent recovery
