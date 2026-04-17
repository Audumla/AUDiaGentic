---
id: task-0266
label: Improve MCP layer robustness and type safety
state: done
summary: Fix root discovery, add Pydantic schemas for operations, structured errors,
  and standard MCP types
spec_ref: spec-019
request_refs:
- request-17
standard_refs:
- standard-0005
- standard-0006
---







# Description

Improve MCP server robustness and type safety. This task addresses root discovery, operation schemas, error handling, and protocol compliance.

**Changes:**
1. **Root discovery**: Use `.audiagentic/` marker, prioritize `AUDIAGENTIC_ROOT` env var
2. **Pydantic schemas**: Strict JSON schema for `tm_edit` operations
3. **Structured errors**: Custom `PlanningError` with suggestions
4. **Protocol compliance**: Remove `_wrap`, use standard MCP types
5. **Documentation**: Update MCP_README.md with concurrency limitations

# Acceptance Criteria

- Root discovery checks `AUDIAGENTIC_ROOT` env var first, then searches for `.audiagentic/`
- Clear error message if project root not found
- `tm_edit` operations validated by Pydantic schema before execution
- Invalid operations return structured error with suggestion
- `_wrap` removed, responses use standard MCP types
- MCP_README.md updated with concurrency limitations and new error format
- All existing tools still work correctly
- Smoke test proves MCP server starts and tools execute

# Notes

File locking and performance optimizations deferred to V2. Atomic writes already implemented in task-0243.
