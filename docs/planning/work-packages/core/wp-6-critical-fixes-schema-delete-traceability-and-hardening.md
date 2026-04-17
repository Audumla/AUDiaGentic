---
id: wp-6
label: 'Critical fixes: schema, delete, traceability, and hardening'
state: done
summary: Verify relation-schema assumptions, implement soft delete and hard-delete
  counter safety, add bidirectional request traceability, prevent duplicates, improve
  validation feedback, and add integration coverage
plan_ref: plan-10
task_refs:
- ref: task-195
  seq: 1000
- ref: task-196
  seq: 1001
- ref: task-197
  seq: 1002
- ref: task-198
  seq: 1003
- ref: task-199
  seq: 1004
- ref: task-200
  seq: 1005
- ref: task-201
  seq: 1006
---




# Objective

Deliver the focused planning-core hardening slice defined by `request-6` and `spec-002`: relation-schema verification, delete safety, correct counter behavior, traceability, duplicate prevention, clearer validation feedback, and integration coverage.

# Scope of This Package

- task-183: Verify real relation schema contract and remove stale meta.task_refs assumption
- task-184: Automatic counter sync after hard deletions
- task-185: Soft delete functionality (tm_delete)
- task-186: Auto-reference updates for plans and tasks
- task-187: Duplicate detection for requests and specs
- task-188: Improved schema validation error messages
- task-189: Integration tests for all critical fixes

# Inputs

- spec-2 (implementation specification)
- plan-5 (execution plan)
- Existing codebase: `api.py`, `tm_helper.py`, `id_gen.py`, `val_mgr.py`

# Instructions

1. **task-0183**: Verify schema-compliant relation placement and remove stale planning assumptions
2. **task-0185**: Implement tm_delete() with soft/hard modes
3. **task-0184**: Integrate sync_counter() into hard delete operations
4. **task-0186**: Extend auto-reference updates to plans/tasks
5. **task-0187**: Add duplicate detection to prevent duplicate creation
6. **task-0188**: Improve validation error messages for better UX
7. **task-0189**: Add integration tests to verify all fixes work together

Execute in order: 0195 → 0197 → 0196 → 0198 → 0199 → 0200 → 0201

# Required Outputs
- Verified schema-compliant relation handling
- tm_delete() function with soft delete default
- Automatic counter sync after hard deletions
- Bidirectional traceability (request ↔ spec/plan/task)
- Cleaned planning guidance for relation placement
- Duplicate detection for requests and specs
- Clear validation error messages with examples
- Integration test suite for all critical fixes
- Updated validation that passes

Execution result: the planning-core hardening slice has been implemented. The repo now supports soft delete and hard delete with safe counter behavior, plan/task request traceability, exact-label duplicate guards for requests/specs, clearer validation messages, and focused regression coverage. The stale `meta.task_refs` assumption was removed from this slice so the implementation matches the live schemas.
# Acceptance Checks

1. `tm_validate()` returns no errors
2. Relation fields remain aligned with the live schemas
3. `tm_delete("task-XXXX")` soft deletes by default
4. Counter syncs automatically after hard delete (not soft delete)
5. Creating spec/plan/task with request_refs preserves reverse traceability through the planning graph/indexes
6. No ID gaps are filled (auditability preserved)
7. Duplicate detection prevents creating requests/specs with same label
8. Validation errors include expected format examples
9. Integration tests pass for all scenarios

# Non-Goals

- Duplicate detection caching beyond the first-pass duplicate guard
- Undo/rollback
- Audit trail
- Performance optimizations
- Bulk operations
