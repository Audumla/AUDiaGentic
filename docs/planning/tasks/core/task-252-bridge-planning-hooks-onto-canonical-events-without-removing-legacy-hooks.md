---
id: task-252
label: Bridge planning hooks onto canonical events without removing legacy hooks
state: done
summary: Preserve current planning hook behavior while routing compatible post-commit
  behavior through canonical events during transition — complete
spec_ref: spec-23
request_refs:
- request-17
standard_refs:
- standard-5
- standard-6
---










# Description

Migrate planning hooks to events per inventory from task-0262. This task wires hook-driven flows through canonical events while preserving current behavior during transition.

**Migration approach:**
1. For each high-priority hook from task-0262:
   - Create event subscription that replicates hook behavior
   - Keep hook functional via compatibility bridge
   - Test both paths work identically
2. Update documentation to mark hooks as deprecated
3. Verify no user-visible behavior changes

**Example migration:**
```python
# Old: hook in hooks.yaml
# task.after_state_change → some_action()

# New: event subscription
bus.subscribe("planning.item.state.changed", lambda e: some_action(e))
```

# Acceptance Criteria

- High-priority hooks from task-0262 migrated to events
- Hook behavior preserved via compatibility bridge
- No user-visible behavior changes
- Hooks marked deprecated in documentation
- Unit tests cover: compatibility path, event path equivalence
- Smoke test proves planning workflows function after migration

# Implementation

**Event Publishing** (`src/audiagentic/planning/app/api.py`):
- `_publish_event()` method publishes events to EventBus with optional integration (try/except)
- All planning API operations now publish events after successful completion
- EventBus integration is optional - API works without it

**Migrated hooks:**
- ✅ `after_create` → `planning.item.created.{kind}`
- ✅ `after_update` → `planning.item.updated.{kind}`
- ✅ `before_state_change` → `planning.item.state.will-change.{kind}`
- ✅ `after_state_change` → `planning.item.state.changed.{kind}`
- ✅ `after_delete` → `planning.item.deleted.{kind}`
- ✅ `after_reconcile` → `planning.reconciled.planning`

**Integration points:**
- `PlanningAPI.new()` - after_create
- `PlanningAPI.create_with_content()` - after_create
- `PlanningAPI.update()` - after_update
- `PlanningAPI.update_content()` - after_update
- `PlanningAPI.state()` - after_state_change
- `PlanningAPI.delete()` - after_delete
- `PlanningAPI.reconcile()` - after_reconcile

**State Propagation Engine Integration:**
The `StatePropagationEngine` is automatically initialized in `PlanningAPI.__init__()` when the EventBus is available. It subscribes to `planning.item.state.changed` events and handles automatic state propagation across planning hierarchies (task→wp→plan→spec).

# Notes

Depends on: task-262 (inventory). Legacy hook removal is task-0263.

## Implementation Status: Complete ✅ (2026-04-15)

All hooks have been migrated to canonical events. The hook system files (`hooks.py`, `hook_bridge.py`) have been removed (task-0263). Event publishing is integrated into all planning API operations with optional EventBus integration. The StatePropagationEngine is automatically initialized and handles state propagation across planning hierarchies.
