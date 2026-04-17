---
id: task-196
label: Fix FastMCP empty-list serialization
state: done
summary: Patch FastMCP response serialization to emit single content block for empty
  lists and None
spec_ref: spec-3
---


# Description

Ensure MCP tools returning empty lists or `None` still emit a usable response payload instead of disappearing into zero content blocks.

# Acceptance Criteria

1. Empty-list MCP tools return a stable wrapped payload
2. `None` results are distinguishable from void/error responses
3. Affected planning MCP tools are protected by a consistent wrapper

# Notes

- Implemented via the `tool_with_empty_list_fix` wrapper in `tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py`
- Covered by the passing MCP tool-call suite
