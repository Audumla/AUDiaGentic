---
id: wp-8
label: Fix PlanningAPI and MCP gaps
state: in_progress
summary: 'Implement 9 fixes: section-mode regex, wp move, claims TTL, hook payloads,
  batch meta, status shape, empty-list serialization, and root isolation'
plan_ref: plan-15
task_refs:
- ref: task-199
  seq: 1000
- ref: task-200
  seq: 2000
- ref: task-201
  seq: 3000
- ref: task-202
  seq: 4000
- ref: task-203
  seq: 5000
- ref: task-204
  seq: 6000
- ref: task-205
  seq: 7000
- ref: task-206
  seq: 8000
- ref: task-207
  seq: 9000
---









# Objective

Bring the planning hardening work tracked under `spec-003` into a consistent state by recording completed fixes and isolating the remaining MCP root-selection gap.

# Scope of This Package

- Mark completed API/MCP fixes as done where code and tests prove delivery
- Leave root-isolation work active until isolated MCP mutation tests are no longer xfailed
- Update task notes so future implementers can see why a task is done or still open

# Inputs

- `request-7`
- `spec-003`
- `tests/integration/planning/test_planning_api_coverage.py`
- `tests/integration/planning/test_mcp_tool_calls.py`
- current planning code in `src/audiagentic/planning/` and `tools/mcp/audiagentic-planning/`

# Instructions

- Use passing tests as the standard for completed tasks.
- Do not mark the root-isolation tasks done until the xfailed isolation class is genuinely implemented.
- Keep the documentation trail concise but specific enough to explain the state decisions.

# Required Outputs

- Updated task states for the implemented fixes
- Request/spec/plan/wp states that no longer imply either “nothing started” or “everything finished”
- Notes tying the remaining open work to MCP isolation

# Acceptance Checks

- Completed fixes are marked `done` only where current code and tests support that claim
- Remaining MCP isolation work is still visible in active tasks
- Planning validation passes after the documentation updates

# Non-Goals

- Implementing the remaining root-isolation feature in this documentation pass
- Reworking unrelated planning requests/specifications
