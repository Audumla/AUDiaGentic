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

Use the MCP tools directly. The server already publishes the tool names and argument schema. Each tool has a description explaining its purpose.

### Creating planning documents

- `tm_new_request(label, summary)` — Create a new Request
- `tm_new_spec(label, summary, request_refs=None)` — Create a Specification linked to Requests
- `tm_new_plan(label, summary, spec=None)` — Create a Plan linked to a Specification
- `tm_new_task(label, summary, spec, domain="core", target=None, parent=None, workflow=None)` — Create a Task with spec and optional target packet
- `tm_new_wp(label, summary, plan, domain="core", workflow=None)` — Create a WorkPackage in a Plan
- `tm_new_standard(label, summary)` — Create a Standard (coding style, docs requirement, etc.)
- `tm_create_with_content(kind, label, summary, content, ...)` — Create any item with initial markdown content

### Querying & viewing

- `tm_list(kind=None)` — List items by kind (request, spec, plan, task, wp, standard)
- `tm_show(id)` — Full view of a single item with all metadata
- `tm_extract(id, with_related=False, with_resources=False)` — Extract item with optional related items and resources
- `tm_status()` — Summary counts by kind and state
- `tm_next_tasks(state="ready", domain=None)` — List Tasks in a state
- `tm_next_items(kind="task", state="ready", domain=None)` — List items by kind and state

### Mutating planning items

- `tm_update(id, label=None, summary=None, append=None)` — Update label, summary, or body text
- `tm_state(id, new_state)` — Change state (ready → in_progress → done, etc.)
- `tm_move(id, domain)` — Move item to a different domain (core → contrib)
- `tm_relink(src, field, dst, seq=None, display=None)` — Update links (spec, parent, related items)
- `tm_package(plan, tasks, label, summary, domain="core")` — Group Tasks into a WorkPackage

### Content editing (markdown sections)

- `tm_get_content(id)` — Get full markdown content of a document
- `tm_update_content(id, content, mode="replace", section=None, position=None)` — Replace, append, or insert content
- `tm_get_section(id, section)` — Get a named section (heading) by name
- `tm_set_section(id, section, content)` — Replace a named section
- `tm_append_section(id, section, content)` — Append to a named section
- `tm_get_subsection(id, section_path)` — Get nested sections using dot notation (e.g., "section.subsection" or "section/subsection")

### Documentation surfaces & profiles

- `tm_list_doc_surfaces()` — List documentation surfaces (generated views for different audiences)
- `tm_get_doc_surface(surface_id)` — Get a specific documentation surface
- `tm_list_reference_docs()` — List reference documentation
- `tm_list_request_profiles()` — List request templates/profiles
- `tm_get_request_profile(profile_id)` — Get a specific request profile
- `tm_list_support_docs(supports_id=None, role=None)` — List supporting (sidecar) documentation
- `tm_doc_sync_requirements(kind, profile_pack="standard")` — Get doc sync requirements for an item kind
- `tm_pending_doc_updates(kind, profile_pack="standard")` — List pending doc updates

### Governance & constraints

- `tm_standards(id)` — List applicable standards (coding styles, docs rules) for an item
- `tm_list_standards()` — List all standard planning documents
- `tm_get_standard(standard_id, with_related=False, with_resources=False)` — Get a standard with metadata and body
- `tm_claim(kind, id, holder, ttl=None)` — Claim ownership to prevent concurrent edits
- `tm_unclaim(id)` — Release ownership
- `tm_claims(kind=None)` — List active claims

### System operations

- `tm_validate()` — Validate all items against schemas; returns list of errors
- `tm_index()` — Re-index all documents (scan, parse, rebuild indices)
- `tm_reconcile()` — Fix filesystem/state inconsistencies
- `tm_events(tail=20)` — Get recent planning events from the log
- `tm_verify_structure()` — Health check: verify directories, configs, and API accessibility

## Guidance

- **Do use these tools for:** Planning-domain CRUD, state changes, validation, queries, doc editing, and governance
- **Don't use this server for:** Provider execution, prompt launching, runtime job control, general code edits, or agent job submission (that's AUDiaGentic's job dispatcher)
  
