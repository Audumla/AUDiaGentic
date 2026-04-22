---
id: task-205
label: Implement tm_bulk_state for state transitions
state: cancelled
summary: Add tm_bulk_state(ids, new_state, summary_only) operation optimized for bulk
  state changes
spec_ref: spec-11
request_refs: []
standard_refs:
- standard-5
- standard-6
---








# Description

Cancelled with `spec-008` after the owning request record was removed. Recreate this task under a new request if bulk state support is resumed.

# Acceptance Criteria

Cancelled with parent specification.

# Notes

This task was never fleshed into implementation-ready detail before the request chain disappeared.
