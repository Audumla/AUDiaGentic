---
id: task-251
label: Implement state propagation engine for planning hierarchies
state: done
summary: Create propagation logic that subscribes to planning.item.state.changed and
  cascades state changes up hierarchy
spec_ref: spec-20
request_refs:
- request-18
standard_refs:
- standard-5
- standard-6
---






# Description

Implement planning state propagation engine. This task owns subscribing to `planning.item.state.changed` events, evaluating parent-child relationships, and applying automatic propagation across task → wp → plan → spec.

**Propagation rules:**
- Any child `in_progress` → parent `in_progress` (if parent is `ready`)
- All children `done` → parent `done`
- Any child `blocked` → parent `blocked` (unless terminal state)
- Rollback: child reverts → parent reverts (if no other children in target state)

**Key behaviors:**
- Subscribe to `planning.item.state.changed` events
- **Use ASYNC mode by default (non-blocking, eventual consistency)**
- Skip replayed events (`is_replay: true`) unless opt-in via config
- Skip events with `propagation_depth >= 10` (cycle detection)
- Emit new event for each propagation step (enables chaining)
- Respect config from task-0252
- Idempotent: safe to run multiple times on same event
- **Log all propagation attempts to `.audiagentic/planning/meta/propagation_log.json`**
- **Batch parent state changes to minimize disk I/O**
- Conflict resolution: `blocked` > `in_progress` > `ready` > `draft`
- Terminal states (`done`, `archived`) not overwritten

# Acceptance Criteria

- Task→WP propagation: `in_progress`, `done`, `blocked` scenarios work (ASYNC)
- WP→Plan propagation: same rules apply
- Plan→Spec propagation: same rules apply
- Conflict resolution: `blocked` > `in_progress` > `ready` > `draft`
- Terminal states (`done`, `archived`) not overwritten
- Rollback handling: child revert triggers parent revert
- Replayed events skipped (`is_replay: true`)
- Events with `propagation_depth >= 10` rejected and logged
- Each propagation emits `planning.item.state.changed` event with incremented depth
- **All propagation attempts logged to `propagation_log.json`**
- **Batched writes reduce disk I/O compared to naive implementation**
- Integration tests cover: forward propagation, rollback, conflicts, idempotency, cycle detection
- Smoke test proves planning state transitions work with propagation enabled (ASYNC mode)

# Notes

Depends on: task-248 (EventBus), task-0252 (config), task-0253 (planning emits events), task-0264 (async queue). Audit tool is task-0265.
