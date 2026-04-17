---
id: task-177
label: Implement MCP helper root configurability
state: done
summary: Add root parameter to all helper functions and set_root/reset_root for isolated
  operations
spec_ref: spec-5
meta:
  task_refs:
  - ref: wp-0008
    seq: 1000
---






# Description

Add root parameter to all MCP helper functions and implement set_root/reset_root for isolated operations.

**Status: IMPLEMENTED**

All implementation work for task-0177 is complete:
- Added set_root(root) and reset_root() functions to tm_helper.py
- Added _get_root() helper to get current root (auto-detected or explicitly set)
- Added root: Path | None = None parameter to all helper functions
- All 40+ helper functions now support explicit root parameter
- Backward compatible - existing code works without changes
- Tests verify isolated operations work correctly
- 49/49 planning tests pass

Files modified:
- tools/planning/tm_helper.py - Added root configurability to all functions
- tests/integration/planning/test_mcp_helper_root.py - New tests for root configurability

Usage examples:
- tm.set_root(Path("/path/to/project")) - Set custom root
- tm.reset_root() - Reset to auto-detected root
- tm.new_task("Label", "Summary", "spec-0001", root=Path("/path")) - Use explicit root
