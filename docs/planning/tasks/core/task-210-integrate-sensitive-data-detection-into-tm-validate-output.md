---
id: task-210
label: Integrate sensitive data detection into tm_validate output
state: done
summary: Update tm_validate() to emit sensitive data warnings in validation output
  as non-blocking warnings
spec_ref: spec-12
request_refs: []
standard_refs:
- standard-5
- standard-6
---













---
id: task-213
label: Expose tm_check_sensitive_data in MCP and tm_helper
state: draft
summary: Add tm_check_sensitive_data MCP tool and ensure tm_helper exports check_sensitive_data function
spec_ref: spec-9
---

# Implementation

## MCP Tool Registration
Add to `tools/mcp/audiagentic-planning/audiagentic_planning_mcp_claude.py`:

```python
@mcp.tool(description="Check a planning item for sensitive data patterns (AWS keys, API keys, passwords, tokens) in body content")
def tm_check_sensitive_data(id: str) -> dict[str, Any]:
    return tm.check_sensitive_data(id)
```

## Verify tm_helper Export
Ensure `tools/planning/tm_helper.py` exports:
```python
def check_sensitive_data(id_: str, root: Path | None = None) -> dict[str, Any]:
    # Implementation in task-0212
```

## Verification
- Tool appears in MCP tools/list response
- Tool has description
- Tool accepts `id: str` parameter
- Tool returns dict with correct structure
- Tool is callable via both MCP and direct import

## Notes
- Standalone tool, not integrated into validation
- Opt-in: agents call explicitly
- No validation API changes

# Description

Expose the detection function as an MCP tool so agents can call it. Register tm_check_sensitive_data in the MCP server and ensure it's properly exported from tm_helper.
