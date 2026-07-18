# foundation/workflow/

Generic workflow infrastructure for resource lifecycle state machines,
config-driven state propagation, lifecycle actions, transition validation,
and item creation templates.

## Purpose

The workflow layer provides reusable lifecycle mechanics for any host component
that manages stateful resources. The host owns storage, configuration, event
subscription, and side effects. The workflow package only validates transitions
and delegates reads/writes/events through protocol interfaces.

Core rule: workflow code has no dependency on any host component or concrete
storage backend.

## Architecture

```text
Host component
    |
    +-- StateMachine             -> validates transitions and lifecycle actions
    +-- TransitionEngine         -> minimal declared-transition validator
    +-- StatePropagationEngine   -> calculates passive parent/child propagation
    +-- WorkflowActionExecutor   -> creates related resources from templates
    +-- FrontmatterBuilder       -> assembles item metadata from config defaults
```

## StateMachine

`state_machine.py` validates state transitions against host-provided workflow
config, applies lifecycle metadata, persists through the host context, publishes
the configured state-change event, and applies immediate lifecycle cascades.

Key methods:

- `state(id_, new_state, reason, actor, metadata)` transitions one resource.
- `apply_action(name, id_, reason, actor, metadata)` applies a named lifecycle action.
- `is_terminal(id_)` checks membership in the configured `terminal` state set.

Lifecycle metadata tokens:

- `now`
- `actor`
- `actor_or_system`
- `reason`
- `reason_or_empty`
- `null`

Immediate cascade is relationship-scoped. A lifecycle action can cascade from a
source kind to related target kinds, but targets are resolved only through
configured reference fields.

## TransitionEngine

`transition_engine.py` is the minimal declared-transition validator: a frozen
transition table plus terminal-state set with `check(current, target)` and
`is_known_state(state)`. `transitions.py` provides the YAML workflow loader and
the functional helpers (`load_workflow`, `transition_allowed`, `is_known_state`,
`states_in_set`) used by component record stores.

## StatePropagationEngine

`propagation/engine.py` is a passive propagation utility. It does not subscribe
to events. A host calls `propagate()` after a state change, then applies returned
transitions with `apply_propagation()`.

Key methods:

- `propagate(item_id, new_state, metadata)` returns target transition tuples.
- `apply_propagation(target_id, target_state, source_id, source_state, metadata)` applies one propagation.
- `validate_hierarchy(item_id)` validates parent/child state consistency.
- `heal_hierarchy(item_id, auto_fix)` suggests or applies safe consistency fixes.

Propagation rules use semantic state sets such as `initial`, `active`,
`blocked`, `complete`, and `terminal`, not hardcoded state names.

`propagation/rules.py` contains built-in generic rule functions (`rule_none`,
`rule_parent_in_set`, `rule_parent_not_in_set`, `rule_all_children_in_set`,
`action_complete_parent`). Rules receive the engine plus IDs/config and operate
only through workflow interfaces. `propagation/workflow_item_api.py` defines the
smaller `WorkflowItemAPI` protocol used by propagation.

No production host is wired to the propagation engine yet; it is retained by
sponsor direction for planned plan-item parent/child state consistency.

## WorkflowActionExecutor

`actions.py` executes config-defined creation/update templates.

- `execute(action_name, context)` creates related resources and applies updates.
- `render(value, context)` renders placeholders recursively.

Placeholder behavior:

- `{key}` returns the original typed value.
- Mixed text uses `str.format(**context)`.
- Unknown placeholders raise `ValueError`.

## FrontmatterBuilder

`frontmatter.py` assembles item metadata from host config defaults and provided
values. It supports scalar refs, scalar ref lists, and relationship lists.

This helper is item-metadata oriented. Hosts that do not use frontmatter can
skip it and implement their own resource builder while still using the state
machine.

## Invocation

The `invocation/` subdirectory provides workflow invocation and execution utilities.

- `invocation/models.py` — data models for invocation steps and run context
- `invocation/from_spec.py` — build executable steps from descriptor specs
- `invocation/runner.py` — orchestrates step execution with error handling

## ID Generation

`id_gen.py` provides `next_id(counter_path, id_prefix)` for file-backed,
process-safe sequential IDs. Hosts with database or service-assigned IDs can
ignore this helper.

## Interfaces

`interfaces.py` defines the host contracts:

- `ItemView` neutral DTO for workflow items.
- `WorkflowConfig` supplies states, transitions, semantic state sets, lifecycle
  actions, event type, and reference metadata.
- `WorkflowContext` supplies lookup/scan/find, save, event publishing, creation,
  relinking, state transition, and index refresh.

## File Map

| File | Responsibility |
|------|----------------|
| `state_machine.py` | State transitions, lifecycle actions, immediate cascades |
| `transition_engine.py` | Minimal declared-transition validator |
| `propagation/engine.py` | Passive state propagation orchestration |
| `propagation/propagation_config.py` | YAML loader, validator, callable resolver |
| `propagation/parents.py` | Parent/child reference resolution |
| `propagation/rules.py` | Built-in propagation rules and actions |
| `propagation/rule_evaluator.py` | Rule evaluation over semantic state sets |
| `propagation/healing.py` | Hierarchy validation and opt-in healing |
| `propagation/log.py` | Structured propagation audit log |
| `propagation/workflow_item_api.py` | Minimal propagation host protocol |
| `transitions.py` | YAML workflow loader and transition helpers |
| `actions.py` | Template-driven workflow action executor |
| `frontmatter.py` | Metadata/frontmatter builder helper |
| `id_gen.py` | File-backed sequential ID generation |
| `interfaces.py` | Workflow host protocols and `ItemView` DTO |
| `util.py` | Small generic helpers |
| `invocation/models.py` | Invocation data models |
| `invocation/from_spec.py` | Descriptor-spec step construction |
| `invocation/runner.py` | Step execution orchestrator |
