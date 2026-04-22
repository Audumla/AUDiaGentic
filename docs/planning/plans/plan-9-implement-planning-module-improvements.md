---
id: plan-9
label: Implement planning module improvements
state: done
summary: Execute a focused planning-core hardening slice covering relation-schema
  verification, soft delete, hard-delete counter safety, traceability, duplicate prevention,
  validation feedback, and regression tests
spec_refs:
- spec-4
work_package_refs:
- ref: wp-11
  seq: 1000
---










# Objectives

1. Verify the real relation schema contract and remove stale implementation assumptions
2. Enable safe deletion of planning items without manual filesystem operations
3. Ensure ID counters remain correct after hard deletions
4. Establish bidirectional traceability between requests and downstream items
5. Prevent accidental duplicate request/spec creation
6. Make validation feedback more actionable for common schema mistakes
7. Add integration coverage for the full hardening slice

# Delivery Approach

**Phase 1: Relation-Schema Verification (task-0183)**
- Verify schemas/managers remain aligned for task/spec/work-package relations
- Remove stale planning assumptions about `meta.task_refs`
- Verify validation passes

**Phase 2: Soft Delete (task-0185)**
- Implement tm_delete() with soft/hard modes
- Add deleted_at timestamp and reason fields
- Ensure soft deleted items remain queryable

**Phase 3: Counter Sync (task-0184)**
- Integrate sync_counter() into hard delete operations
- Verify no ID reuse (gaps preserved)
- Test next ID generation after deletes

**Phase 4: Auto-References (task-0186)**
- Extend existing spec auto-update to plans and tasks
- Add validation for referenced requests
- Test bidirectional traceability

**Phase 5: Duplicate Detection (task-0187)**
- Add first-pass duplicate checks for request/spec creation
- Keep behavior explainable and intentionally limited to exact label duplicates for the first pass

**Phase 6: Validation Feedback (task-0188)**
- Improve error messages for common schema and reference-shape mistakes
- Keep the changes within the existing validator architecture

**Phase 7: Integration Coverage (task-0189)**
- Add end-to-end coverage for the combined hardening slice
- Verify interactions between delete flow, counter handling, references, duplicates, and validation

# Dependencies

- spec-2 (implementation specification)
- wp-6 (critical fixes work package)
- Existing sync_counter() function in id_gen.py
- Existing _add_source_ref() pattern (partially implemented for specs)
- Existing validator implementation in val_mgr.py
- Existing helper and MCP surfaces that need to stay aligned with the core API
