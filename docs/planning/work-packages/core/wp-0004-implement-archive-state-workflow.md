---
id: wp-0004
label: Implement archive state workflow
state: draft
summary: Add archive functionality to planning core with tm_archive, tm_restore, and
  filtering
plan_ref: plan-0005
task_refs:
- ref: task-0022
  seq: 1000
- ref: task-0023
  seq: 2000
- ref: task-0024
  seq: 3000
- ref: task-0025
  seq: 4000
- ref: task-0026
  seq: 5000
- ref: task-0027
---


# Objective

Implement archive state workflow in the planning core to enable safe removal of obsolete content while preserving historical records.

# Scope of This Package

- Add `archived` state to planning object state machine
- Implement `tm_archive` and `tm_restore` functions
- Update query functions to filter archived objects
- Add archive metadata to data model
- Update validation and display functions

# Inputs

- spec-0003: Archive state workflow specification
- Existing planning objects that may need archiving

# Instructions

1. **task-0022**: Add archived state to state machine
   - Update state validation logic
   - Define valid transitions: done→archived, archived→draft/ready/in_progress

2. **task-0023**: Implement tm_archive and tm_restore functions
   - Create tm_archive(id, reason, actor)
   - Create tm_restore(id, state, actor)
   - Add archive_metadata field to data model

3. **task-0024**: Update tm_list with archive filter
   - Add include_archived parameter
   - Update tm_next_tasks to exclude archived objects

4. **task-0025**: Update tm_validate with archive rules
   - Validate archive metadata for archived objects
   - Flag cross-references to archived objects

5. **task-0026**: Update tm_show to include archive metadata
   - Display archive metadata for archived objects
   - Show restoration history if applicable

# Required Outputs

- Working tm_archive function
- Working tm_restore function
- Updated tm_list with archive filtering
- Updated tm_next_tasks excluding archived objects
- Updated tm_validate with archive rules
- Updated tm_show with archive metadata

# Acceptance Checks

1. Can archive an object in `done` state
2. Cannot archive an object not in `done` state
3. Can restore an archived object to active state
4. tm_list excludes archived objects by default
5. tm_list includes archived objects when include_archived=true
6. tm_next_tasks excludes archived objects
7. tm_validate flags cross-references to archived objects
8. tm_show displays archive metadata for archived objects

# Non-Goals

- Deleting archived objects (preservation only)
- Automatic archiving (manual operation only)
- Bulk archive operations (single object at a time)
