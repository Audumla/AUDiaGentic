# foundation/workflow/

Generic workflow infrastructure for state machines, config-driven state propagation, lifecycle actions, and item management. Used by planning and other workflow-driven components.

## Purpose

The workflow layer provides the engine that drives planning item lifecycles: state transitions, propagation rules, lifecycle actions, frontmatter assembly, and relationship management. All behavior is **config-driven** — no hardcoded state names, transitions, or propagation rules in the code.

**Key design principle:** The workflow engine is passive infrastructure. It provides methods for calculating and applying changes, but does NOT subscribe to events or trigger actions automatically. The owner component (planning) registers event handlers that call these utilities.

## Architecture

```
PlanningAPI (owner)
    │
    ├── StateMachine          ─→ validates transitions, applies lifecycle actions
    ├── StatePropagationEngine ─→ calculates state propagations (passive, config-driven)
    ├── WorkflowActionExecutor ─→ batch item creation via config templates
    ├── FrontmatterBuilder    ─→ assembles frontmatter from config defaults
    └── Relationships         ─→ rel_list management
```

## Components

### StateMachine (`state_machine.py`)

Config-driven state transition engine. Validates transitions against configured workflows, applies lifecycle actions, tracks state history, and emits events.

- `state(id_, new_state, reason, actor, metadata)` — transition an item to a new state
  - Validates against workflow config
  - Applies lifecycle action metadata
  - Publishes `planning.item.state.changed` event (SYNC)
  - Triggers cascade rules if configured
  - Rebuilds index
- `apply_action(name, id_, reason, actor, metadata)` — apply a named lifecycle action (e.g., `archive`, `supersede`)
- `apply_metadata(data, event_payload, metadata_rules, timestamp, actor, reason)` — apply lifecycle action metadata tokens
- `cascade(id_, kind, action, actor, reason)` — cascade state changes to related items
- `is_terminal(id_)` — check if item is in a terminal state

**Lifecycle metadata tokens:** `{now}`, `{actor}`, `{actor_or_system}`, `{reason}`, `{reason_or_empty}`, `{null}`

### StatePropagationEngine (`propagation.py`)

Config-driven state propagation engine. **This is a passive utility** — it calculates propagations but does NOT subscribe to events. The owner component (planning) registers event handlers and calls `propagate()` / `apply_propagation()`.

**Usage pattern:**
```python
# In planning component __init__:
self._propagation_engine = StatePropagationEngine(
    ctx=self,
    config_path=self.root / ".audiagentic" / "planning" / "config" / "state_propagation.yaml",
)

# Register event handler:
self._bus.subscribe("planning.item.state.changed", self._on_state_change)

# In _on_state_change handler:
propagations = self._propagation_engine.propagate(item_id, new_state)
for target_id, target_kind, target_state in propagations:
    self._propagation_engine.apply_propagation(
        target_id=target_id,
        target_state=target_state,
        source_id=item_id,
        source_state=new_state,
        metadata=metadata,
    )
```

**Key methods:**
- `propagate(item_id, new_state, metadata)` — returns list of `(target_id, target_kind, target_state)` tuples
- `apply_propagation(target_id, target_state, source_id, source_state, metadata)` — applies a propagation via the planning API
- `validate_hierarchy(item_id)` — validates state consistency for an item and its hierarchy
- `heal_hierarchy(item_id, auto_fix)` — attempts to fix state inconsistencies
- `load_workflow_config()` — loads propagation config from YAML

**Propagation config structure:**
```yaml
global:
  enabled: true
  max_depth: 10

kinds:
  task:
    enabled: true
    parent_kind: wp
    parent_field: task_refs
    state_rules:
      done:
        rule: all_children_in_set
        new_state: done
        when:
          state_set: complete
        actions:
          - action: complete_parent
            required_state_set: complete
            parent_field: wp_ref
            target_state: done
            parent_blocking_set: terminal

rules:
  all_children_in_set:
    enabled: true
    logic: audiagentic.foundation.workflow.propagation_rules.rule_all_children_in_set

actions:
  complete_parent:
    enabled: true
    logic: audiagentic.foundation.workflow.propagation_rules.action_complete_parent

healing:
  auto_fix: false
  log_only: true
```

### Propagation Rules (`propagation_rules.py`)

Configurable rule implementations referenced by name in propagation config:

- **rule_none** — no propagation
- **rule_parent_in_set** — propagate when parent state is in a configured semantic set
- **rule_all_children_in_set** — propagate when all sibling children are in a configured semantic set
- **rule_parent_not_in_set** — propagate when parent state is NOT in a configured semantic set
- **action_complete_parent** — complete parent when all children are in the required state set

All rules operate on **semantic state sets** (e.g., `complete`, `active`, `terminal`), not hardcoded state names.

### WorkflowActionExecutor (`actions.py`)

Generic executor for config-driven workflow actions. Creates items in batches based on config templates with placeholder rendering.

- `execute(action_name, context)` — execute a workflow action (creates items, applies updates)
- `render(value, context)` — render `{placeholder}` templates against context dict

**Placeholder rules:**
- Single placeholder (`{key}`) returns the original typed value
- Mixed text uses `str.format(**context)`
- Lists and dicts render recursively
- Unknown placeholder raises `ValueError`

### FrontmatterBuilder (`frontmatter.py`)

Assembles frontmatter dicts from config defaults and provided values. Handles reference field coercion, seeded references, and creation extra fields.

- `build(kind, id_, label, summary, ...)` — returns complete frontmatter dict
- `_coerce_reference_value(field, value)` — coerces values to match field shape (scalar_ref, scalar_ref_list, rel_list)

### Relationships (`rel.py`)

Utility for managing `rel_list` reference fields (lists of `{ref, seq, display}` dicts).

- `ensure_rel_list(current, ref, seq, display)` — adds or updates a reference, maintains sort order by `seq` then `ref`

### ID Generation (`id_gen.py`)

Thread-safe, process-safe sequential ID generation with file-based locking.

- `next_id(counter_path, id_prefix)` — returns next ID (e.g., `request-1`, `task-42`)
- Uses `.lock` files for process safety
- IDs are raw integers, no zero-padding

### ItemView (`item.py`)

Neutral DTO for workflow items: `kind`, `path`, `data` (frontmatter dict), `body` (markdown body).

### Interfaces (`interfaces.py`)

Protocol definitions for the workflow engine's dependencies:

- **WorkflowConfig** — config methods the engine needs: `initial_state()`, `workflow_for()`, `state_in_set()`, `lifecycle_action()`, `reference_fields()`, etc.
- **WorkflowContext** — runtime operations: `lookup()`, `_scan()`, `_find()`, `_publish_event()`, `new()`, `relink()`, `index()`
- **WorkflowItemAPI** (in `propagation_api.py`) — minimal interface for propagation engine: `lookup()`, `state()`, `_scan()`

### Utilities (`util.py`)

- `slugify(s)` — lowercase, alphanumeric, hyphen-separated
- `now_iso()` — UTC ISO 8601 timestamp
- `body_has_section(body, section)` — checks for `# section` or `## section` in markdown body

## Semantic State Sets

The propagation engine uses semantic state sets defined in workflow config, not hardcoded state names. Common sets:

- **initial** — starting states (e.g., `draft`, `captured`)
- **active** — work-in-progress states (e.g., `ready`, `in_progress`, `review`)
- **blocked** — impeded states (e.g., `blocked`)
- **complete** — successfully finished (e.g., `done`, `verified`)
- **terminal** — end states, no further transitions (e.g., `done`, `cancelled`, `archived`, `superseded`)
- **closed** — all terminal states

State priority is numeric; propagation only upgrades (higher priority), never downgrades.

## Config-Driven Design

All workflow behavior is driven by configuration files:

1. **Workflow definitions** — states, transitions, state sets (in planning config)
2. **Lifecycle actions** — metadata, events, cascades (in planning config)
3. **Propagation rules** — which states propagate, to which parents (in `state_propagation.yaml`)
4. **Workflow actions** — batch creation templates (in planning config)

No state names, transitions, or propagation rules are hardcoded in the code. Adding a new workflow requires only config changes, not code changes.

## Standard References

- **standard-10** (Component architecture standard) — requirements 11-19 cover config-driven design, no hardcoded values, pluggable rule implementations, and passive utilities
- **standard-12** (Event subscription configuration standard) — event type conventions and handler patterns used by workflow events

## File Map

| File | Responsibility |
|------|----------------|
| `state_machine.py` | State transitions, lifecycle actions, cascade, metadata tokens |
| `propagation.py` | StatePropagationEngine — config-driven propagation calculation and application |
| `propagation_rules.py` | Rule implementations: rule_none, rule_parent_in_set, rule_all_children_in_set, etc. |
| `propagation_api.py` | WorkflowItemAPI protocol — minimal interface for propagation engine |
| `actions.py` | WorkflowActionExecutor — batch item creation with placeholder rendering |
| `frontmatter.py` | FrontmatterBuilder — assembles frontmatter from config defaults |
| `rel.py` | Relationships — rel_list management |
| `id_gen.py` | Thread-safe sequential ID generation with file locking |
| `item.py` | ItemView DTO |
| `interfaces.py` | WorkflowConfig, WorkflowContext protocols |
| `util.py` | slugify, now_iso, body_has_section utilities |
