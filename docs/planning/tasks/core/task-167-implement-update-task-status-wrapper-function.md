---
id: task-167
label: Implement update_task_status() wrapper function
state: done
summary: Add single-call wrapper function that updates task state and appends implementation
  notes
spec_ref: spec-8
---










# Description

Add single-call wrapper function that updates task state and appends implementation notes.

**Status: IMPLEMENTED**

All implementation work for task-0170 is complete:
- Created update_task_status() function in tm_helper.py
- Function combines state transition with section append in single call
- Supports custom section (default: description)
- Backward compatible with existing code
- Usage: tm.update_task_status("task-0001", "ready", "Notes here")

Function signature:
```python
def update_task_status(
    id_: str,
    state: str,
    notes: str,
    section: str = "description",
    root: Path | None = None,
) -> dict[str, Any]:
```

Benefits:
- Single tool call instead of two (state + append_section)
- Clear intent - updates state and documents completion together
- Token efficient - reduces API calls
- Consistent with MCP root configurability improvements
