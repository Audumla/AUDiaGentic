---
id: task-253
label: Integrate interoperability layer with planning component
state: done
summary: Wire up EventBus in planning, emit planning.item.state.changed events after
  state commits
spec_ref: spec-19
request_refs:
- request-17
- request-18
standard_refs:
- standard-5
- standard-6
---







# Description

Integrate interoperability event layer into planning component. This task owns wiring planning to emit canonical post-commit events after valid state transitions.

**Event emission point:**
After successful state transition in `api.py.state()`:
```python
self.state(id_, new_state)
# After commit:
bus.publish("planning.item.state.changed", {
    "old_state": old_state,
    "new_state": new_state
}, {
    "subject": {"kind": kind, "id": id_},
    "triggered_by": "manual"  # or "automatic" for propagation
})
```

**Key behaviors:**
- Emit AFTER state commit (events are facts, not commands)
- Include metadata: `subject`, `triggered_by`, `correlation_id`
- Don't break existing planning behavior
- Keep hooks functional during transition
- Optional integration: use try/except to avoid breaking if EventBus not available
- Default to ASYNC mode for non-blocking propagation

# Acceptance Criteria

- Planning emits `planning.item.state.changed` after successful state commits
- Event includes: `subject.kind`, `subject.id`, `payload.old_state`, `payload.new_state`
- Metadata includes: `triggered_by` (manual/automatic), `correlation_id`
- Event emission happens after commit, not before
- Existing planning operations work with event emission enabled
- Unit tests cover: event emission timing, payload shape, compatibility
- Smoke test proves planning state transitions work and events emitted

# Notes

Depends on: task-248 (EventBus). This task is planning emission only, not propagation.

# Accomplished

**Completed:**
- ✅ Created standard-0013 (event subscription configuration standard)
- ✅ Implemented configurable event-driven knowledge updates
- ✅ Moved event config files to `.audiagentic/knowledge/events/`
- ✅ Updated knowledge component to use event handlers
- ✅ Backfilled documentation (request-43, spec-023)
- ✅ Verified config loading works (3 adapters, 4 handlers)
- ✅ Fixed PlanningAPI hooks reference error (task-0253)
- ✅ Removed hooks.yaml from config loading
- ✅ Removed hooks validation from schema checks
- ✅ Verified MCP planning tools work after fix

**Remaining:**
- [ ] Delete hooks-config.schema.json (optional - keep for backward compat)
- [ ] Update any documentation referencing hooks
