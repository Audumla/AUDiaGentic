---
id: task-237
label: Consolidate MCP tools
state: draft
summary: Consolidate 28 MCP tools into 7-8 top-level tools with backward compatibility
spec_ref: spec-20
parent_task_ref: wp-14
request_refs:
- request-15
standard_refs:
- standard-5
- standard-6
---










# Description
Consolidate the knowledge MCP surface into a smaller set of top-level tools only if that work is still genuinely needed. Current code and docs suggest the consolidation target may already be effectively satisfied, so this task should first verify whether it is still real work or just stale planning noise.

# Acceptance Criteria
1. Confirm whether a consolidation gap still exists in the current MCP surface.
2. If a gap exists, group the tools into the agreed top-level surfaces without breaking aliases.
3. If no gap exists, mark the task and dependent work as redundant or superseded.
4. Backward compatibility remains intact for any existing tool names that callers still use.
5. Tests and docs reflect the final decision.

# Notes
- This task is likely narrower than the summary implies because the current MCP already exposes grouped operations.
- Validate against the live MCP server before doing implementation work here.
