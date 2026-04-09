---
id: request-0007
label: 'Planning module critical fixes: schema, soft delete, and traceability'
state: captured
summary: Fix schema mismatches (task_refs placement), implement soft delete with counter
  sync, and add automatic bidirectional reference updates for traceability
source_refs: []
current_understanding: ''
open_questions: []
---





# Notes

## Auto-Reference Updates (NEW)

**Feature:** When creating specs/plans/tasks with `request_refs`, automatically update the referenced request's `source_refs` to create bidirectional traceability.

**Implementation:**
- Hook in `api.new()` for specs: when `request_refs=[request-0007]` is provided, auto-add `spec-XXXX` to `request-0007.source_refs`
- Same for plans and tasks
- Ensures traceability without manual updates

**Status:** Partially implemented (spec auto-update added to api.py), needs:
- Extension to plans and tasks
- Validation that referenced requests exist
- Error handling for missing requests
- Backfill for existing items

**Priority:** P1 (High - improves traceability significantly)
