---
id: spec-11
label: Unified workflow states for all planning item types
state: draft
summary: Specification for aligning request workflow states with spec/plan/task/wp
  workflows
request_refs:
- request-12
task_refs: []
standard_refs:
- standard-9
---


# Purpose

Align request workflow states with spec/plan/task/wp workflows to provide consistent lifecycle management across all planning item types.

# Scope

## In Scope

- Define unified state machine for requests
- Update workflows.yaml with request states
- Update validation rules for new states
- Update tm_state() transitions
- Update CLI state commands
- Migrate existing requests to new states

## Out of Scope (v1)

- Changing state names for spec/plan/task/wp
- Adding new states beyond current set
- Complex conditional transitions

# Requirements

## 1. Unified States

All planning item types use the same states:

```yaml
planning:
  workflows:
    request:
      default: unified
      named:
        unified:
          initial: draft
          values: [draft, captured, distilled, ready, in_progress, done, cancelled, archived]
          transitions:
            draft: [captured, distilled, cancelled, archived]
            captured: [draft, distilled, ready, cancelled, archived]
            distilled: [draft, captured, ready, in_progress, cancelled, archived]
            ready: [draft, in_progress, cancelled, archived]
            in_progress: [ready, done, cancelled, archived]
            done: [archived]
            cancelled: [archived]
            archived: [draft, captured]
```

## 2. State Semantics

- `draft`: Initial intake, not yet logged
- `captured`: Logged but not refined
- `distilled`: Requirements clarified, open questions identified
- `ready`: Ready for implementation
- `in_progress`: Being worked on
- `done`: Complete
- `cancelled`: Abandoned
- `archived`: Closed out, preserved for history

## 3. Migration Strategy

For existing requests:
- `captured` → `captured` (no change)
- `distilled` → `distilled` (no change)
- `closed` → `done`
- `superseded` → `cancelled`
- `archived` → `archived` (no change)

## 4. Validation Updates

Update val_mgr.py to:
- Check state transitions against workflow config
- Validate state consistency across linked items
- Warn about deprecated states

## 5. CLI Updates

Update tm.py to:
- Accept all states for --state parameter
- Show available states per item type
- Handle state migration for existing items

# Constraints

- **Backward compatible**: Old states still accepted during migration period
- **Config-driven**: States defined in workflows.yaml, not hardcoded
- **Validated**: All transitions checked against config
- **Documented**: State semantics documented in each item type

# Acceptance Criteria

- [ ] workflows.yaml updated with unified request states
- [ ] State transitions validated against config
- [ ] Migration script for existing requests
- [ ] CLI updated to support all states
- [ ] Validation rules updated
- [ ] All planning tests pass
- [ ] Documentation updated

# Notes

This is a foundational change that affects all planning operations. The unified states make the system more predictable and easier to learn.
