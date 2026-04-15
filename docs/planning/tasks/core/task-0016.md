---
id: task-0016
label: Add archived state to planning state machine
state: draft
summary: Implement archived state, define valid state transitions (done→archived,
  archived→restored)
spec_ref: spec-004
---



# Description

Add `archived` state to the planning object state machine and define valid state transitions.

## Current States

- `draft` - Object is being created/edited
- `ready` - Object is ready for work
- `in_progress` - Work is actively being done
- `done` - Work is complete

## New State

- `archived` - Object is obsolete but preserved for history

## State Transitions

```
draft -> ready -> in_progress -> done -> archived
   |                           ^
   +----------- archived <------+
```

### Valid Transitions

| From State | To State | Condition |
|------------|----------|-----------|
| `draft` | `ready` | Object is complete and ready |
| `ready` | `in_progress` | Work begins |
| `in_progress` | `done` | Work is complete |
| `in_progress` | `ready` | Work paused, not complete |
| `done` | `archived` | Object is obsolete |
| `archived` | `draft` | Object restored to draft |
| `archived` | `ready` | Object restored to ready |
| `archived` | `in_progress` | Object restored to in_progress |

### Invalid Transitions

- `draft` → `archived` (must go through done)
- `ready` → `archived` (must go through in_progress and done)
- `in_progress` → `archived` (must complete first)
- `archived` → `done` (must restore first)

# Acceptance Criteria

1. `tm_state` accepts `archived` as valid state
2. `tm_state` validates transitions correctly
3. Invalid transitions return error with clear message
4. Archive state persists in object storage
5. State machine documentation updated

# Notes

- Archive state is additive; existing transitions remain unchanged
- Backward compatibility: existing objects without archive state work as before
- State validation must check both state validity and transition validity
