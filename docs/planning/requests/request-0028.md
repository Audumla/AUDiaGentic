---
id: request-0028
label: Unify planning workflow states across all item types
state: captured
summary: Align request workflow states with spec/plan/task/wp workflows for consistent
  lifecycle management
source: workflow-consistency
current_understanding: Request workflow states (captured, distilled, closed, superseded,
  archived) differ from spec/plan/task/wp workflows (draft, ready, in_progress, blocked,
  done, cancelled, archived). This creates inconsistency in state transitions, validation
  rules, and UI/CLI behavior.
open_questions:
- Should requests use the same states as specs/tasks, or a simplified subset?
- What state transitions should be allowed for each request state?
- How do we handle existing requests when migrating to new states?
- Do we need a migration script or can we do it incrementally?
- Should validation rules differ by item type even with same state names?
context: Align request workflow states with other planning item workflows for consistency
standard_refs:
- standard-0001
spec_refs:
- spec-0047
---


# Understanding

Request workflow states (captured, distilled, closed, superseded, archived) differ from spec/plan/task/wp workflows (draft, ready, in_progress, blocked, done, cancelled, archived). This creates inconsistency in state transitions, validation rules, and UI/CLI behavior.

# Open Questions

- Should requests use the same states as specs/tasks, or a simplified subset?
- What state transitions should be allowed for each request state?
- How do we handle existing requests when migrating to new states?
- Do we need a migration script or can we do it incrementally?
- Should validation rules differ by item type even with same state names?
# Notes
