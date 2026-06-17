# foundation/workflow/

Generic workflow infrastructure for resource lifecycle state machines,
config-driven state propagation, lifecycle actions, relationship handling, and
item creation templates.

## Purpose

The workflow layer provides reusable lifecycle mechanics for any host component
that manages stateful resources. The host owns storage, configuration, event
subscription, and side effects. The workflow package only validates transitions,
calculates related state changes, and delegates reads/writes/events through
protocol interfaces.

Core rule: workflow code has no dependency on any host component or concrete
storage backend.

## Architecture

```text
Host component
    |
    +-- StateMachine             -> validates transitions and lifecycle actions
    +-- StatePropagationEngine   -> calculates passive parent/child propagation
    +-- WorkflowActionExecutor   -> creates related resources from templates
    +-- FrontmatterBuilder       -> assembles item metadata from config defaults
    +-- Relationships            -> manages reference-list values
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

## Rules

`propagation/rules.py` contains built-in generic rule functions:

- `rule_none`
- `rule_parent_in_set`
- `rule_parent_not_in_set`
- `rule_all_children_in_set`
- `action_complete_parent`

Rules receive the engine plus IDs/config and operate only through workflow
interfaces.

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
skip it and implement their own resource builder while still using the state and
propagation engines.

## Relationships

`rel.py` provides `Relationships.ensure_rel_list()` for list values shaped as
`{"ref": "...", "seq": ..., "display": "..."}`.

## Invocation

The `invocation/` subdirectory provides workflow invocation and execution utilities.

- `invocation/models.py` — data models for invocation steps and run context
- `invocation/steps.py` — step definition and sequencing primitives
- `invocation/runner.py` — orchestrates step execution with error handling

## ID Generation

`id_gen.py` provides `next_id(counter_path, id_prefix)` for file-backed,
process-safe sequential IDs. Hosts with database or service-assigned IDs can
ignore this helper.

## Interfaces

`interfaces.py` defines the host contracts:

- `WorkflowConfig` supplies states, transitions, semantic state sets, lifecycle
  actions, event type, and reference metadata.
- `WorkflowContext` supplies lookup/scan/find, save, event publishing, creation,
  relinking, state transition, and index refresh.
- `propagation/api.py` defines the smaller `WorkflowItemAPI` protocol used by
  propagation.

## File Map

| File | Responsibility |
|------|----------------|
| `state_machine.py` | State transitions, lifecycle actions, immediate cascades |
| `propagation/engine.py` | Passive state propagation orchestration |
| `propagation/config.py` | YAML loader, validator, callable resolver |
| `propagation/parents.py` | Parent/child reference resolution |
| `propagation/rules.py` | Built-in propagation rules and actions |
| `propagation/healing.py` | Hierarchy validation and opt-in healing |
| `propagation/log.py` | Structured propagation audit log |
| `propagation/api.py` | Minimal propagation host protocol |
| `actions.py` | Template-driven workflow action executor |
| `frontmatter.py` | Metadata/frontmatter builder helper |
| `rel.py` | Relationship-list helper |
| `id_gen.py` | File-backed sequential ID generation |
| `item.py` | `ItemView` DTO |
| `interfaces.py` | Workflow host protocols |
| `util.py` | Small generic helpers |
| `invocation/models.py` | Invocation data models |
| `invocation/steps.py` | Step definition and sequencing |
| `invocation/runner.py` | Step execution orchestrator |
