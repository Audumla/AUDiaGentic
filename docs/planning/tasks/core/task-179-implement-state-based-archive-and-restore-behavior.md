---
id: task-179
label: Implement state-based archive and restore behavior
state: done
summary: Extend planning state transition behavior to support archive and restore
  metadata, events, and guardrails
spec_ref: spec-1
meta:
  task_refs:
  - ref: wp-0009
    seq: 1001
---



# Description

Implement archive and restore behavior through the planning core's canonical state transition model.

## Requirements

### Archive Transition

```python
def tm_state(
    id_: str,
    new_state: str,
    reason: str | None = None,
    actor: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Change planning item state, including archive transitions.
    
    Args:
        id_: Item ID to change
        new_state: Target state (`archived` for archive)
        reason: Optional archive reason
        actor: Optional actor identifier
        root: Optional project root
    
    Returns:
        Dict with id, state, archived_at, archived_by, reason
    """
```

### Restore Transition

```python
def tm_state(
    id_: str,
    new_state: str,
    actor: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Change planning item state, including restore transitions.
    
    Args:
        id_: Item ID to change
        new_state: Target state for restore from archive, as allowed by the item workflow
        actor: Optional actor identifier
        root: Optional project root
    
    Returns:
        Dict with id, state, restored_at, restored_by
    """
```

## Implementation

- Extend the planning core state/lifecycle path
- Update `tools/planning/tm_helper.py` and underlying planning API surfaces as needed
- Keep any MCP convenience exposure aligned to the same core semantics
- Record archive metadata (archived_at, archived_by, reason)
- Log archive events

## Acceptance Criteria

1. State-driven archive transitions move items to archived state
2. State-driven restore transitions move items back to a valid active state
3. Archive metadata is recorded (timestamp, user, reason)
4. Archive events are logged
5. Archived items cannot be modified directly

# Notes

- Implemented in `PlanningAPI.state()` with archive/restore metadata and event emission.
- Archived items are now protected from normal update, content update, move, and relink mutations until restored.
- Verified by planning API integration tests and coverage tests.
