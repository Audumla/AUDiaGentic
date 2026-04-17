---
id: task-193
label: Fix hook event payloads
state: done
summary: Fix review_stub, report_stub, note_stub hook payloads to have correct structure
spec_ref: spec-3
---


# Description

Align hook stub payloads for review/report/note actions with the event shape expected by the coverage tests.

# Acceptance Criteria

1. `review_stub` emits the expected event payload
2. `report_stub` emits the expected event payload
3. `note_stub` includes the note content in payload

# Notes

- Implemented in `src/audiagentic/planning/app/hook_mgr.py`
- Verified by the `review_stub`, `report_stub`, and `note_stub` coverage tests
