# audiagentic-planning MCP

Minimal planning MCP server for AUDiaGentic.

## Install

```bash
pip install mcp
```

## Server

```bash
python tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py
```

## Generic MCP config

For clients that use an MCP server map:

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

## Tool surface

Use the MCP tools directly. The server already publishes the tool names and argument schema.

- `tm_new_request(label, summary)`
- `tm_new_spec(label, summary, request_refs=None)`
- `tm_new_plan(label, summary, spec=None)`
- `tm_new_task(label, summary, spec, domain="core", target=None, parent=None, workflow=None)`
- `tm_new_wp(label, summary, plan, domain="core", workflow=None)`
- `tm_new_standard(label, summary)`
- `tm_state(id, new_state)`
- `tm_move(id, domain)`
- `tm_update(id, label=None, summary=None, append=None)`
- `tm_relink(src, field, dst, seq=None, display=None)`
- `tm_package(plan, tasks, label, summary, domain="core")`
- `tm_list(kind=None)`
- `tm_show(id)`
- `tm_extract(id, with_related=False, with_resources=False)`
- `tm_next_tasks(state="ready", domain=None)`
- `tm_next_items(kind="task", state="ready", domain=None)`
- `tm_status()`
- `tm_standards(id)`
- `tm_claim(kind, id, holder, ttl=None)`
- `tm_unclaim(id)`
- `tm_claims(kind=None)`
- `tm_validate()`
- `tm_index()`
- `tm_reconcile()`
- `tm_events(tail=20)`

Guidance:
- use MCP tools for planning-domain CRUD, state changes, validation, and queries
- do not use this server for provider execution, prompt launching, runtime job control, or general code edits
  