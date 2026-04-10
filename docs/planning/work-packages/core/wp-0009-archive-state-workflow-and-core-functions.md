---
id: wp-0009
label: Archive state workflow and core functions
state: in_progress
summary: Implement archive state in planning state machine and tm_archive/tm_restore
  functions
plan_ref: plan-0009
task_refs:
- ref: task-0190
  seq: 1000
- ref: task-0191
  seq: 1001
- ref: task-0192
  seq: 1002
- ref: task-0193
  seq: 1003
- ref: task-0194
  seq: 1004
---


# Objective

Implement archive state workflow and core functions for planning items to enable archiving
older or redundant items while maintaining historical records.

# Scope of This Package

- Add archived state to planning state machine
- Implement tm_archive() and tm_restore() helper functions
- Update tm_list() with archive filtering
- Update tm_validate() with archive rules
- Update tm_show() with archive metadata

# Inputs

- spec-0023: Archive state and functionality specification
- Existing planning state machine
- Existing tm_helper functions

# Instructions

1. Add archived state to all planning item kinds
2. Define valid state transitions including archive/restore
3. Implement tm_archive() and tm_restore() in tm_helper.py
4. Update tm_list() to filter archived items
5. Update tm_validate() to skip cross-ref validation for archived items
6. Update tm_show() to include archive metadata

# Required Outputs

- Archived state in planning state machine
- tm_archive() and tm_restore() functions
- Archive filtering in tm_list()
- Archive validation rules in tm_validate()
- Archive metadata in tm_show()

# Acceptance Checks

- [ ] Archived state is defined for all planning kinds
- [ ] State transitions are validated correctly
- [ ] tm_archive() transitions item to archived state
- [ ] tm_restore() transitions item back to ready state
- [ ] tm_list() excludes archived items by default
- [ ] tm_validate() skips cross-ref validation for archived items
- [ ] tm_show() includes archive metadata

# Non-Goals

- Full audit trail system (just basic metadata)
- Automated archiving policies
- Bulk archive operations
- Archive cleanup/sweeping
