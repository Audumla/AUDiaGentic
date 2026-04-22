---
id: task-201
label: Expose head(id) and refined extract controls in MCP and tm_helper
state: done
summary: Add tm_head MCP tool and tm_helper.head() function; update tm_extract to
  expose include_body and write_to_disk options so AI consumers have a clear low-token
  read path
spec_ref: spec-10
request_refs: []
standard_refs:
- standard-5
- standard-6
---












# Description

Expose the new `head(id)` capability and the refined `extract()` controls at the helper and MCP layers.

**`tm_helper.py`**

Add `head(root, id_)` function that calls `api.head(id_)` and returns the index entry dict. Keep it consistent with the existing `show()` pattern.

**`tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py`**

Add a `tm_head` MCP tool:

```python
@mcp.tool()
def tm_head(id: str) -> dict:
    """Return lean index-only metadata for a planning item. No markdown parse. Lowest token cost."""
    return _wrap_tool_result(tm_helper.head(root, id))
```

Update `tm_extract` to expose `include_body` and `write_to_disk` parameters:

```python
@mcp.tool()
def tm_extract(id: str, with_related: bool = False, with_resources: bool = False,
               include_body: bool = True, write_to_disk: bool = True) -> dict:
```

Update tool docstrings to make the cost hierarchy clear to AI consumers:

- `tm_head` — index only, no file parse, minimum tokens
- `tm_show` — full frontmatter, single file parse, no body
- `tm_extract` — body-inclusive, use `include_body=False` to get frontmatter without body

# Acceptance Criteria

- `tm_head` MCP tool exists and returns `{id, kind, label, state, path, deleted}`
- `tm_helper.head()` function exists and is callable from outside MCP
- `tm_extract` MCP tool accepts `include_body` and `write_to_disk` parameters
- Tool descriptions distinguish the three read tiers clearly
- Tests cover `tm_head` returning index data and `tm_extract` with `include_body=False`

# Notes

Depends on task-0201 (head helper) and task-0203 (extract controls). This is the final surface-exposure step — no new logic, only wiring.
