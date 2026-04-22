---
id: wp-6
label: Archive state workflow and core functions
state: done
summary: Implement archive state in planning state machine and state-based archive/restore
  behavior
plan_ref: plan-0009
standard_refs:
- standard-9
task_refs:
- ref: task-187
  seq: 1000
- ref: task-188
  seq: 1001
- ref: task-189
  seq: 1002
- ref: task-190
  seq: 1003
- ref: task-191
  seq: 1004
---










# Objective

Implement archive state workflow and core functions for planning items to enable archiving
older or redundant items while maintaining historical records.

# Scope of This Package

- Add archived state to planning state machine
- Implement state-based archive and restore behavior in the planning core
- Update tm_list() with archive filtering
- Update tm_validate() with archive rules
- Update tm_show() with archive metadata

# Inputs

- spec-1: Archive state and functionality specification
- Existing planning state machine
- Existing tm_helper functions

# Instructions

1. Add archived state to all planning item kinds
2. Define valid state transitions including archive/restore
3. Implement archive and restore behavior through the canonical state/lifecycle machinery rather than separate wrapper-defined semantics
4. Update tm_list() to filter archived items
5. Update tm_validate() to skip cross-ref validation for archived items
6. Update tm_show() to include archive metadata
7. Keep MCP/helper exposure aligned with the planning-core state model

# Required Outputs

- Archived state in planning state machine
- State-based archive and restore behavior in the planning core
- Archive filtering in tm_list()
- Archive validation rules in tm_validate()
- Archive metadata in tm_show()

# Acceptance Checks

- [ ] Archived state is defined for all planning kinds
- [ ] State transitions are validated correctly
- [ ] State-driven archive transitions move items to archived with metadata
- [ ] State-driven restore transitions move items back to ready with metadata
- [ ] tm_list() excludes archived items by default
- [ ] tm_validate() skips cross-ref validation for archived items
- [ ] tm_show() includes archive metadata

# Non-Goals

- Full audit trail system (just basic metadata)
- Automated archiving policies
- Bulk archive operations
- Archive cleanup/sweeping
