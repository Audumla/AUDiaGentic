---
id: plan-6
label: Fix planning API and MCP gaps
state: in_progress
summary: Execute 9 fixes across PlanningAPI and MCP layers to resolve 23 failing tests
  and 32 xfail mutation tests
spec_refs:
- spec-3
work_package_refs: []
---


# Objectives

- Reflect actual completion across the `spec-003` task set instead of leaving the whole chain in `draft`
- Keep the remaining root-isolation work visible and actionable
- Align planning states with current code/test evidence

# Delivery Approach

- Treat the passing planning coverage suite as evidence that tasks `0202` through `0208` are implemented
- Leave the MCP root-isolation slice (`0209` and `0210`) active until the xfailed mutation tests can run against isolated roots
- Update the planning docs first so future work starts from an accurate ledger

# Dependencies

- `spec-003`
- `tests/integration/planning/test_planning_api_coverage.py`
- `tests/integration/planning/test_mcp_tool_calls.py`
