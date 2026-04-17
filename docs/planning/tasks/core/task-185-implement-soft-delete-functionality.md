---
id: task-185
label: Implement soft delete functionality
state: done
summary: Add tm_delete() function that marks items as deleted without removing files,
  with retention policy
spec_ref: spec-2
---



# Description

Implement tm_delete() to allow safe deletion of planning items without manual filesystem operations. Soft delete (default) marks items as deleted while preserving files for audit/recovery. Hard delete removes files.

# Acceptance Criteria

1. `tm_delete(id_)` soft deletes by default (adds deleted: true, deleted_at: timestamp)
2. `tm_delete(id_, hard=True)` permanently removes file
3. Soft deleted items remain queryable via tm_list(include_deleted=True)
4. Deletion reason can be recorded
5. Counter sync is triggered only for hard deletes (task-0184)

# Notes

- Add to `tools/planning/tm_helper.py`
- Add to `src/audiagentic/planning/app/api.py`
- Schema needs `deleted` and `deleted_at` fields added
- Implementation result: added `delete()` to the planning API plus helper, CLI, and MCP surfaces. Soft delete now marks items with `deleted`, `deleted_at`, and optional `deletion_reason`; hard delete removes the file and syncs counters.
