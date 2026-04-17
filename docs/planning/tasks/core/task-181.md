---
id: task-181
label: Update tm_validate with archive validation rules
state: done
summary: Add archive validation rules to tm_validate() for archived items
spec_ref: spec-1
meta:
  task_refs:
  - ref: wp-0009
    seq: 1003
---



# Description

Add archive validation rules to tm_validate() for archived items.

## Requirements

Archived items should have relaxed validation rules:

1. **Required fields still validated**: id, label, state
2. **Optional fields relaxed**: References can be stale
3. **No cross-reference validation**: Archived items don't need valid refs
4. **Content validation skipped**: Archived content is frozen

## Implementation

- Update validation behavior in the planning core
- Add archived state check
- Skip cross-reference validation for archived items
- Still validate required fields
- Report archived-item validation distinctly enough for review/debugging

## Acceptance Criteria

1. Archived items pass validation for required fields
2. Archived items skip cross-reference validation
3. tm_validate() preserves normal validation for active items while skipping archived-item referential checks
4. Non-archived items still fully validated

# Notes

- Implemented in `src/audiagentic/planning/app/val_mgr.py`.
- Archived items now skip referential validation without breaking hook-driven validation flows.
