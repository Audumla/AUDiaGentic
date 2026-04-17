---
id: task-184
label: Implement automatic counter sync on delete
state: done
summary: Add automatic counter synchronization after hard deletions to ensure the
  next ID stays correct without reusing deleted IDs
spec_ref: spec-2
---


# Description

When planning items are hard-deleted, the persisted counter must be synchronized to ensure the next ID generation is correct. This does NOT mean decrementing the counter to prevent gaps; IDs must remain stable and monotonic for auditability.

This task implements automatic calls to `sync_counter()` after hard deletes and ensures the counter never moves backwards, even if the highest existing file has been removed.

# Acceptance Criteria

1. After hard delete operations, `sync_counter()` is called automatically
2. Counter remains monotonic and does not move backwards to reuse deleted IDs
3. Next ID generation after delete produces the correct next sequential ID
4. No decrement logic that would reuse deleted IDs
5. Works for all planning kinds (request, spec, plan, task, wp, standard)

# Notes

- **Do not** implement "decrement to prevent gaps" - this breaks auditability
- **Do** implement safe counter synchronization after hard delete without moving the stored counter backwards
- Gaps in IDs are acceptable and expected when items are deleted
- The counter file stores the highest ID seen, not the count of items
- Implementation result: added automatic counter synchronization after hard deletes only, and updated `sync_counter()` so it never moves the persisted counter backwards. This preserves monotonic IDs and avoids deleted-ID reuse.
