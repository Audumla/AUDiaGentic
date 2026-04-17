---
id: spec-22
label: Auto-state propagation with event subscription implementation specification
state: cancelled
summary: Implement event subscription for StatePropagationEngine to enable automatic
  state propagation across planning hierarchies
request_refs:
- request-20
task_refs:
- ref: task-321
standard_refs:
- standard-1
- standard-5
- standard-6
---






# Purpose


# Scope


# Requirements


# Constraints


# Acceptance Criteria


# Purpose

Implement event subscription wiring to enable automatic state propagation across planning hierarchies. The `StatePropagationEngine` exists with config-driven rules but is never subscribed to events. This spec defines how to wire event subscription while respecting workflow configuration.

# Scope

- Event subscription in `PlanningAPI` or `StatePropagationEngine`
- Workflow-aware propagation triggering
- Failure handling and logging
- Cycle detection implementation
- Integration tests for propagation scenarios

# Requirements

## Event Subscription

The `StatePropagationEngine` must subscribe to `planning.item.state.changed` events upon initialization.

**Requirements:**
- Subscription happens in `__init__` after config is loaded
- Subscription respects global `enabled` flag
- Handler method `_on_state_change` processes events
- Unsubscribe on cleanup (if engine is destroyed)

## Event Handler

The `_on_state_change` handler must process events and trigger propagation.

**Requirements:**
- Extract `item_id` and `new_state` from event payload
- Call existing `propagate()` method
- Apply each propagation by calling `planning_api.state()`
- Log failures but don't re-raise exceptions
- Include `triggered_by: "automatic"` in metadata for propagated changes

## Propagation Application

The `_apply_propagation` method must apply state changes to target items.

**Requirements:**
- Skip if target already in desired state (idempotent)
- Call `planning_api.state()` with `triggered_by: "automatic"` metadata
- Include reason with source item ID
- Use `actor: "system"` for automatic changes
- Catch and log `ValueError` for invalid transitions
- Catch and log other exceptions without re-raising

## Cycle Detection

The propagation must track depth to prevent infinite loops.

**Requirements:**
- Track depth parameter in `propagate()` method
- Check against `max_depth` from config (default 10)
- Log when max depth is reached
- Return empty list to stop propagation
- Depth increments with each propagation level

## Workflow Configuration Respect

Propagation must respect workflow configuration at all levels.

**Requirements:**
- Check global `enabled` first
- Check per-item `propagation.enabled` override
- Check per-kind `enabled` flag
- Respect workflow-specific config if item has `workflow` field
- Return config that disables propagation if any level disables it

## Delivery Mode

Propagation must respect delivery mode configuration.

**Requirements:**
- Default to `DeliveryMode.ASYNC` for non-blocking
- Allow workflow config to override mode
- `fast-track` workflow uses `SYNC` mode for immediate feedback
- Mode affects subscription, not individual propagations

# Acceptance Criteria

1. **Event subscription**: `StatePropagationEngine` subscribes to `planning.item.state.changed` events
2. **Automatic propagation**: State changes trigger propagation without manual intervention
3. **Config respect**: Workflow configuration controls propagation behavior
4. **Cascade propagation**: Changes propagate up the full hierarchy when rules allow
5. **Failure isolation**: Propagation failures don't break original state changes
6. **Cycle detection**: Max depth prevents infinite loops
7. **Per-item override**: Items can disable propagation via frontmatter
8. **Delivery mode**: ASYNC by default, SYNC for fast-track workflow
9. **Logging**: Propagation events are logged for debugging
10. **Tests**: All integration tests pass

# Notes

Cancelled on 2026-04-17 because `request-20` was superseded by implemented subscription wiring and the broader remaining work tracked under `request-18`.
