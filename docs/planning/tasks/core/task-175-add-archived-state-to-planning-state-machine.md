---
id: task-175
label: Add archived state to planning state machine
state: done
summary: Add archived state to planning state machine and define valid transitions
spec_ref: spec-2
meta:
  task_refs:
  - ref: wp-0009
    seq: 1000
---



















# Description

Add archived state to planning state machine and define valid state transitions.

## Requirements

1. Add "archived" state to all planning item kinds (request, spec, plan, task, wp, standard)
2. Define valid transitions:
   - draft → archived (direct archive)
   - ready → archived (archive ready items)
   - in_progress → archived (archive in-progress items with warning)
   - done → archived (archive completed items)
   - archived → a valid active state for that item kind (restore from archive)
3. Archive state should be read-only (cannot modify archived items)
4. Archived items should still be queryable but excluded from default views

## Implementation

- Update `src/audiagentic/planning/app/api.py` state machine
- Add archived state to workflow definitions
- Implement archive validation rules
- Ensure archive semantics remain canonical in workflow/core planning logic, not only in MCP wrappers

## Acceptance Criteria

1. Archived state is defined in all workflow configurations
2. State transitions are validated correctly
3. Archived items cannot be modified (state transitions rejected)
4. Archived items are excluded from default tm_list() output
5. Archived items can be restored through the state transition model

# Notes

- Implemented in workflow configuration and planning-core state handling.
- Added `archived` transitions for request, spec, plan, task, wp, and standard workflows.
- Verified by planning integration tests covering archive and restore state transitions.
