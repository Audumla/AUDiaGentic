---
id: request-20
label: Auto-state propagation with event subscription
state: superseded
summary: Enable automatic state propagation across planning hierarchies via event
  subscription driven by workflow configuration
source: user feedback on incomplete propagation implementation
guidance: standard
current_understanding: The StatePropagationEngine exists with config-driven rules
  in state_propagation.yaml, but it is never subscribed to planning.item.state.changed
  events. Events are published but nothing consumes them. Need event subscription
  logic that respects workflow configuration (enabled/disabled per workflow, per-kind,
  per-item).
open_questions:
- Should subscription be global (one subscriber for all events) or per-workflow?
- How should propagation failures be handled (retry, log, skip)?
- Should propagation be synchronous (blocking) or asynchronous (background)?
standard_refs:
- standard-1
- standard-5
- standard-6
spec_refs:
- spec-22
---







# Understanding

The StatePropagationEngine exists with config-driven rules in state_propagation.yaml, but it is never subscribed to planning.item.state.changed events. Events are published but nothing consumes them. Need event subscription logic that respects workflow configuration (enabled/disabled per workflow, per-kind, per-item).

# Open Questions

- Should subscription be global (one subscriber for all events) or per-workflow?
- How should propagation failures be handled (retry, log, skip)?
- Should propagation be synchronous (blocking) or asynchronous (background)?
# Notes
Superseded on 2026-04-17. The gap described here is no longer current: planning now subscribes to `planning.item.state.changed` in `src/audiagentic/planning/app/api.py`. Remaining state-propagation follow-up is tracked under `request-18`, so this narrower request is redundant.
# Understanding

The state propagation infrastructure is built but incomplete. The `StatePropagationEngine` exists with:
- Config-driven rules in `.audiagentic/interoperability/state_propagation.yaml`
- Per-workflow configuration (default, fast-track, conservative, documentation)
- Per-kind and per-item override support
- Validation logic for config correctness

However, the engine is instantiated in `PlanningAPI.__init__()` but never subscribed to events. When `api.state()` publishes `planning.item.state.changed` events, nothing consumes them to trigger propagation.

# Problem

State propagation is manual and incomplete:
1. **No event subscription**: The `StatePropagationEngine` sits idle after instantiation
2. **No automatic triggering**: Propagation must be manually called via `engine.propagate()`
3. **Config exists but unused**: Workflow configuration defines rules but they're never applied
4. **Manual state maintenance**: Users must manually update parent states when children change

This defeats the purpose of the interoperability layer and forces manual state management across hierarchies.

# Desired Outcome

Automatic state propagation that respects configuration:

**Observable outcomes:**
1. When a task transitions to `done`, its parent WP automatically evaluates propagation rules
2. When all tasks in a WP are `done`, the WP transitions to `done` (if configured)
3. Propagation cascades up: Task → WP → Plan → Spec → Request
4. Workflow configuration controls behavior:
   - `fast-track`: Aggressive propagation, synchronous mode
   - `conservative`: Minimal propagation, opt-in per-item
   - `documentation`: No propagation
5. Per-item overrides in frontmatter can disable propagation for specific items
6. Propagation failures are logged but don't break the original state change

# Constraints

- Must not break existing planning operations
- Propagation failures must not rollback the original state change
- Must respect per-item, per-kind, and per-workflow configuration
- Cycle detection must prevent infinite propagation loops
- Must work with both SYNC and ASYNC delivery modes
- Python 3.10+ compatibility

# Verification Expectations

1. **Event subscription**: `StatePropagationEngine` subscribes to `planning.item.state.changed` events
2. **Automatic propagation**: State changes trigger propagation without manual intervention
3. **Config respect**: Workflow configuration controls propagation behavior
4. **Cascade propagation**: Changes propagate up the full hierarchy when rules allow
5. **Failure isolation**: Propagation failures don't break original state changes
6. **Cycle detection**: Max depth prevents infinite loops
7. **Per-item override**: Items can disable propagation via frontmatter
