---
id: plan-001
label: Implement archive functionality in planning core
state: draft
summary: Add archive state to state machine, implement tm_archive/tm_restore, update
  tm_list/tm_validate/tm_show
spec_refs:
- spec-004
work_package_refs:
- ref: wp-0004
---




# Objectives

Add archive state workflow to the planning core to enable safe removal of obsolete content while preserving historical records.

# Delivery Approach

## Phase 1: Core State Machine (task-0016)
- Add `archived` state to state machine
- Define valid state transitions
- Update state validation logic

## Phase 2: Archive Functions (task-0017)
- Implement `tm_archive(id, reason, actor)` function
- Implement `tm_restore(id, state, actor)` function
- Add archive metadata to data model

## Phase 3: Query Filtering (task-0018)
- Update `tm_list` with `include_archived` parameter
- Update `tm_next_tasks` to exclude archived objects
- Update `tm_next_items` to exclude archived objects

## Phase 4: Validation (task-0019)
- Add archive metadata validation
- Flag cross-references to archived objects
- Update validation error messages

## Phase 5: Display (task-0020)
- Update `tm_show` to include archive metadata
- Display archive reason and timestamp
- Show restoration history

# Dependencies

- spec-0003: Archive state workflow specification
