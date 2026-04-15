---
id: spec-020
label: Planning state propagation over events specification
state: ready
summary: Automatic state transitions using interoperability layer events
request_refs:
- request-017
- request-018
task_refs:
- ref: task-0276
- ref: task-0277
- ref: task-0278
- ref: task-0279
- ref: task-0280
- ref: task-0281
- ref: task-0282
- ref: task-0283
- ref: task-0284
- ref: task-0285
- ref: task-0286
- ref: task-0287
- ref: task-0288
- ref: task-0289
- ref: task-0290
- ref: task-0291
- ref: task-0292
- ref: task-0293
standard_refs:
- standard-0005
- standard-0006
---




# Purpose

Implement automatic state propagation across planning item hierarchies using the interoperability event layer. When child items change state, parent items shall automatically transition to appropriate states based on configurable rules, eliminating manual state management and ensuring consistency.

This spec defines planning-specific event consumption and state propagation logic built on top of the interoperability event layer (spec-019).

**Consistency Model:** State propagation uses **asynchronous eventual consistency** by default. This means hierarchies may be temporarily inconsistent during propagation, but will converge to consistent state. A recovery/audit tool is provided to repair inconsistencies from crashes or failures.

**Implementation Order:**
1. task-0257: Package scaffolding (src/audiagentic/planning/propagation/)
2. task-0248: EventBus core (from req-0035)
3. task-0252: Config system (state_propagation.yaml)
4. task-0251: State propagation engine (handler logic)
5. task-0253: Planning integration (emit events)
6. task-0261: Knowledge event handler (cross-component)
7. task-0265: Audit CLI command
8. task-0256: Integration tests
9. task-0255/0290/0291: Hook migration (optional)

# Scope

**In Scope:**
- Automatic state propagation rules for task→wp→plan→spec hierarchy
- Event-driven state transitions using interoperability layer (ASYNC mode by default)
- Configurable propagation rules per workflow
- Conflict resolution for competing state changes
- State rollback handling (e.g., task done→ready)
- Manual state override support with warnings
- Idempotency for replayed events
- **Propagation logging for recovery/audit**
- **Cycle detection via propagation_depth limits**
- **Batched state updates to minimize disk I/O**

**Out of Scope:**
- Changes to existing state machine definitions (workflows remain same)
- Retroactive state fixes for existing items (audit tool handles this)
- Cross-plan or cross-spec state dependencies
- Interoperability layer implementation (covered in spec-019)
- **Synchronous immediate propagation (too slow, risky for file-based system)**

# Requirements

## Functional Requirements

### SP-1: Task to Work Package Propagation
- When any task in WP transitions to `in_progress`, WP shall transition to `in_progress` (if currently `ready`)
- When all tasks in WP transition to `done`, WP shall transition to `done`
- When any task in WP transitions to `blocked`, WP shall transition to `blocked` (unless already in terminal state)
- Propagation shall be triggered by `planning.item.state.changed` events
- **Propagation shall use ASYNC mode by default (non-blocking, eventual consistency)**
- **Sync mode available via config for low-latency local scenarios**

### SP-2: Work Package to Plan Propagation
- When any WP in Plan transitions to `in_progress`, Plan shall transition to `in_progress` (if currently `ready`)
- When all WPs in Plan transition to `done`, Plan shall transition to `done`
- When any WP in Plan transitions to `blocked`, Plan shall transition to `blocked` (unless already in terminal state)

### SP-3: Plan to Specification Propagation
- When any Plan linked to Spec transitions to `in_progress`, Spec shall transition to `in_progress` (if currently `ready`)
- When all Plans linked to Spec transition to `done`, Spec shall transition to `done`
- When any Plan linked to Spec transitions to `blocked`, Spec shall transition to `blocked` (unless already in terminal state)

### SP-4: Event Subscription and Chaining
- Propagation logic shall subscribe to `planning.item.state.changed` events
- Subscription shall filter by `subject.kind` metadata (task, wp, plan)
- Handler shall be replay-safe (check `is_replay` flag, skip if replayed)
- Each propagation step shall emit its own `planning.item.state.changed` event with incremented `propagation_depth`
- **Events with `propagation_depth >= max_depth` (default: 10) shall be logged but not propagated**
- **Events with `correlation_id` in current chain shall be skipped (cycle detection)**

### SP-5: Configurable Rules
- Propagation rules shall be configurable in `.audiagentic/planning/config/state_propagation.yaml`
- Default rules shall match SP-1 through SP-3
- Rules shall support: `trigger_event`, `target_kind`, `condition`, `action`
- Workflows can override defaults via `workflow_name: overrides:` section
- Rules can be disabled globally via config for debugging
- **Config shall include `mode: ASYNC` or `mode: SYNC` (default: ASYNC)**

### SP-6: Conflict Resolution
- When multiple children trigger different parent states simultaneously, priority shall be: `blocked` > `in_progress` > `ready` > `draft`
- Terminal states (`done`, `archived`, `cancelled`) shall not be overwritten by propagation
- Manual state changes shall take precedence over automatic propagation (with warning logged)

### SP-7: Rollback Handling
- When task reverts from `done` to `ready`, parent WP shall revert from `done` to `in_progress` (if no other done tasks)
- Rollback shall propagate up hierarchy similarly to forward transitions
- Rollback events shall include `rollback: true` metadata flag

### SP-8: Manual Override Support
- Users shall be able to manually set state via `state(id, new_state, force=true)`
- Forced state changes shall log warning if conflicting with propagation rules
- Forced states shall be marked with `manually_overridden: true` in metadata
- Propagation shall respect forced states (not overwrite them)

### SP-9: Idempotency
- State propagation handlers shall be idempotent (safe to run multiple times)
- Handlers shall check current state before applying transitions
- Replayed events shall not trigger propagation (check `is_replay` flag)
- Duplicate events with same `id` shall be ignored

### SP-10: Propagation Logging and Recovery
- **All propagation attempts shall be logged to `.audiagentic/planning/meta/propagation_log.json`**
- Log entries shall include: `event_id`, `source_item`, `target_item`, `old_state`, `new_state`, `timestamp`, `status` (success/failed/skipped)
- **Failed propagations shall be logged with full context for debugging**
- **`audiagentic planning audit --fix` command shall:**
  - Scan all planning items for inconsistent hierarchies
  - Report items where parent state doesn't match children
  - Optionally auto-fix by re-running propagation logic
  - Log all fixes applied

### SP-11: Batched State Updates
- **Propagation shall batch parent state changes to minimize disk I/O**
- Multiple state changes in same propagation chain shall be collected and written in single operation where possible
- **Memory-first cache: state changes written to memory first, async flush to disk**
- Batch size and flush interval configurable (default: flush after each chain completes)

## Non-Functional Requirements

### SP-12: Performance
- **ASYNC mode: state change API returns immediately (<10ms), propagation happens in background**
- **SYNC mode: full propagation chain completes within 500ms for typical hierarchies (≤50 items)**
- Propagation shall not block the original state change operation (ASYNC mode)
- Large hierarchies (100+ items) shall complete within 5 seconds

### SP-13: Reliability
- **Partial propagation failures shall be logged but not leave items in permanently inconsistent state**
- **Audit tool (SP-10) can repair inconsistencies from crashes**
- Failed propagations shall be logged with full context for debugging
- System shall recover gracefully from propagation errors

### SP-14: Observability
- All state changes (manual and automatic) shall be logged to event log
- Propagation chain shall be traceable via `correlation_id` in events
- State change history shall include `triggered_by` field (manual vs automatic)
- **Propagation log (SP-10) provides audit trail for all propagation attempts**

# Module Structure

```
src/audiagentic/planning/propagation/
├── __init__.py              # Package exports
├── engine.py                # StatePropagationEngine class
├── rules.py                 # Propagation rules evaluation
├── config.py                # Config loading (task-0252)
├── log.py                   # Propagation logging (task-0265)
├── audit.py                 # Audit & repair logic (task-0265)
└── handlers.py              # Event handlers (task-0251)

.audiagentic/planning/config/
├── state_propagation.yaml   # Propagation configuration
└── meta/
    └── propagation_log.json # Propagation attempt log
```

## Propagation Engine Architecture

```
planning.item.state.changed event
  -> EventBus (spec-019)
      -> StatePropagationEngine
          -> RulesEvaluator (evaluate SP-1 through SP-3)
          -> ConflictResolver (SP-6)
          -> StateWriter (batched updates, SP-11)
              -> propagation_log.json (SP-10)
                  -> Audit CLI (task-0265)
```

**StatePropagationEngine:** Subscribes to events, evaluates rules, triggers state changes
**RulesEvaluator:** Implements propagation rules (task→wp, wp→plan, plan→spec)
**ConflictResolver:** Resolves competing state changes (blocked > in_progress > ready)
**StateWriter:** Batches state updates, writes to propagation log
**Audit CLI:** Scans for inconsistencies, repairs hierarchies

## Code Examples

### Propagation Handler (task-0251)

```python
from audiagentic.interoperability import EventBus
from audiagentic.planning.propagation import StatePropagationEngine

class StatePropagationHandler:
    def __init__(self):
        self.engine = StatePropagationEngine()
        self.bus = EventBus.get_instance()
        self._subscribe()
    
    def _subscribe(self):
        """Subscribe to planning state changes."""
        self.bus.subscribe(
            "planning.item.state.changed",
            self._on_state_change,
            mode="ASYNC"  # Default: async propagation
        )
    
    def _on_state_change(self, event_type, payload, metadata):
        """Handle state change events."""
        # Skip replayed events
        if metadata.get("is_replay"):
            return
        
        # Skip if propagation depth exceeded
        if metadata.get("propagation_depth", 0) >= 10:
            return
        
        kind = payload.get("subject", {}).get("kind")
        new_state = payload.get("new_state")
        item_id = payload.get("subject", {}).get("id")
        
        # Evaluate propagation rules
        parent_states = self.engine.evaluate_rules(kind, item_id, new_state)
        
        # Apply state changes
        for target_kind, target_id, target_state in parent_states:
            self.engine.apply_state_change(
                kind=target_kind,
                id=target_id,
                new_state=target_state,
                triggered_by="automatic",
                correlation_id=metadata.get("correlation_id"),
                propagation_depth=metadata.get("propagation_depth", 0) + 1
            )
```

### Rules Evaluator (task-0251)

```python
class RulesEvaluator:
    """Evaluate propagation rules for task→wp→plan→spec."""
    
    def evaluate_rules(self, child_kind, child_id, new_state):
        """
        Evaluate propagation rules and return list of (parent_kind, parent_id, new_state).
        
        Rules (SP-1 through SP-3):
        - Any child in_progress → parent in_progress (if ready)
        - All children done → parent done
        - Any child blocked → parent blocked (unless terminal)
        """
        propagations = []
        
        if child_kind == "task":
            propagations.extend(self._task_to_wp(child_id, new_state))
        elif child_kind == "wp":
            propagations.extend(self._wp_to_plan(child_id, new_state))
        elif child_kind == "plan":
            propagations.extend(self._plan_to_spec(child_id, new_state))
        
        return propagations
    
    def _task_to_wp(self, task_id, new_state):
        """Task to WP propagation (SP-1)."""
        wp = self._get_task_parent(task_id)
        if not wp:
            return []
        
        tasks = self._get_wp_tasks(wp["id"])
        
        if new_state == "in_progress":
            # Any task in_progress → WP in_progress (if ready)
            if wp["state"] == "ready":
                return [("wp", wp["id"], "in_progress")]
        
        elif new_state == "done":
            # All tasks done → WP done
            if all(t["state"] == "done" for t in tasks):
                return [("wp", wp["id"], "done")]
        
        elif new_state == "blocked":
            # Any task blocked → WP blocked (unless terminal)
            if wp["state"] not in ("done", "archived"):
                return [("wp", wp["id"], "blocked")]
        
        return []
    
    def _wp_to_plan(self, wp_id, new_state):
        """WP to Plan propagation (SP-2)."""
        # Similar logic for WP→Plan
        pass
    
    def _plan_to_spec(self, plan_id, new_state):
        """Plan to Spec propagation (SP-3)."""
        # Similar logic for Plan→Spec
        pass
```

### Config Example (task-0252)

```yaml
# .audiagentic/planning/config/state_propagation.yaml

# Global enable/disable
enabled: true

# Propagation mode: SYNC (blocking) or ASYNC (background)
mode: ASYNC

# Max propagation depth (cycle detection)
max_depth: 10

# Batch settings
batch:
  enabled: true
  size: 10  # Batch up to 10 state changes
  flush_after_chain: true  # Flush after propagation chain completes

# Default propagation rules
defaults:
  task:
    in_progress:
      action: trigger_wp_in_progress
      condition: wp_state == ready
    done:
      action: check_all_tasks_done_for_wp
      condition: all_tasks_done
    blocked:
      action: trigger_wp_blocked
      condition: wp_state not in (done, archived)
  
  wp:
    in_progress:
      action: trigger_plan_in_progress
      condition: plan_state == ready
    done:
      action: check_all_wps_done_for_plan
      condition: all_wps_done
    blocked:
      action: trigger_plan_blocked
      condition: plan_state not in (done, archived)
  
  plan:
    in_progress:
      action: trigger_spec_in_progress
      condition: spec_state == ready
    done:
      action: check_all_plans_done_for_spec
      condition: all_plans_done
    blocked:
      action: trigger_spec_blocked
      condition: spec_state not in (done, archived)

# Workflow-specific overrides
workflows:
  agile_sprint:
    enabled: true
    overrides:
      task:
        done:
          # In agile, WP goes in_progress when first task done
          action: trigger_wp_in_progress
          condition: any_task_done
  waterfall:
    enabled: true
    overrides:
      wp:
        done:
          # In waterfall, wait for all WPs before spec done
          action: check_all_wps_done_for_plan
          condition: all_wps_done

# Manual override behavior
manual_override:
  enabled: true
  log_warning: true  # Log warning when manual override conflicts with propagation
  force_allowed: true  # Allow force=true to override propagation
```

### Propagation Log Format

```json
// .audiagentic/planning/meta/propagation_log.json
[
  {
    "event_id": "evt_abc123",
    "source_kind": "task",
    "source_id": "task-001",
    "target_kind": "wp",
    "target_id": "wp-001",
    "old_state": "ready",
    "new_state": "in_progress",
    "triggered_by": "automatic",
    "correlation_id": "corr_xyz789",
    "propagation_depth": 1,
    "timestamp": "2026-04-14T12:34:56Z",
    "status": "success",
    "batch_id": "batch_001"
  },
  {
    "event_id": "evt_abc124",
    "source_kind": "wp",
    "source_id": "wp-001",
    "target_kind": "plan",
    "target_id": "plan-001",
    "old_state": "ready",
    "new_state": "in_progress",
    "triggered_by": "automatic",
    "correlation_id": "corr_xyz789",
    "propagation_depth": 2,
    "timestamp": "2026-04-14T12:34:57Z",
    "status": "success",
    "batch_id": "batch_001"
  }
]
```

# Constraints

## Technical Constraints
- Must use interoperability layer events (spec-019) for all propagation
- Must not modify existing state machine validation logic
- Must work with existing workflow definitions in `.audiagentic/planning/config/workflows.yaml`
- **Markdown files have no ACID guarantees; eventual consistency is acceptable**

## Architectural Constraints
- Propagation logic shall be in planning component, not interoperability layer
- Must not introduce circular dependencies
- Must maintain backward compatibility with manual state management
- Events are facts, not commands: state changes happen inside planning component, events announce after commit
- **Async propagation is required for cross-component scenarios to avoid write storms**

## Operational Constraints
- Existing items shall not be auto-updated (only new state changes trigger propagation)
- Propagation can be disabled globally via config for debugging
- Must provide CLI command to manually trigger propagation audit/fix
- **Users must run `audiagentic planning audit --fix` after crashes to repair inconsistencies**

# Event Contract

## Events Emitted

### planning.item.state.changed
```yaml
type: planning.item.state.changed
subject:
  kind: task|wp|plan|spec
  id: task-0112
payload:
  old_state: ready
  new_state: in_progress
metadata:
  triggered_by: manual|automatic
  correlation_id: evt_...
  rollback: false
  propagation_depth: 0  # incremented on each propagation step
  manually_overridden: false
```

## Events Consumed

### planning.item.state.changed
- Filter: `subject.kind` in (task, wp, plan)
- Skip if: `metadata.is_replay == true` or `metadata.propagation_depth >= 10`
- Action: Evaluate propagation rules, emit new event if parent state changes

# Acceptance Criteria

## AC-1: Task to WP Propagation Works
- [ ] Creating task and setting to `in_progress` automatically sets WP to `in_progress` (ASYNC)
- [ ] Setting all tasks in WP to `done` automatically sets WP to `done`
- [ ] Setting any task to `blocked` automatically sets WP to `blocked`
- [ ] Events are emitted for each state change in propagation chain
- [ ] Propagation completes within 5 seconds for typical hierarchies

## AC-2: WP to Plan Propagation Works
- [ ] WP `in_progress` triggers Plan `in_progress`
- [ ] All WPs `done` triggers Plan `done`
- [ ] Any WP `blocked` triggers Plan `blocked`

## AC-3: Plan to Spec Propagation Works
- [ ] Plan `in_progress` triggers Spec `in_progress`
- [ ] All Plans `done` triggers Spec `done`
- [ ] Propagation chain is traceable via event correlation IDs

## AC-4: Configurable Rules Work
- [ ] Default rules work without config file
- [ ] Custom rules in `state_propagation.yaml` are loaded and applied
- [ ] Workflow-specific overrides take precedence over defaults
- [ ] Propagation can be disabled globally via config
- [ ] SYNC/ASYNC mode configurable (default: ASYNC)

## AC-5: Conflict Resolution Works
- [ ] `blocked` state takes priority over `in_progress`
- [ ] Terminal states (`done`, `archived`) are not overwritten
- [ ] Manual `force=true` state changes work and are logged

## AC-6: Rollback Handling Works
- [ ] Task `done` → `ready` reverts WP state appropriately
- [ ] Rollback events include `rollback: true` metadata
- [ ] Rollback propagates up hierarchy correctly

## AC-7: Idempotency and Cycle Detection Work
- [ ] Replaying events doesn't re-trigger state changes
- [ ] Duplicate events with same ID are ignored
- [ ] Handler can run multiple times safely
- [ ] Events with `propagation_depth >= 10` are rejected and logged
- [ ] Cycle detection via `correlation_id` prevents infinite loops

## AC-8: Propagation Logging and Recovery Work
- [ ] All propagation attempts logged to `propagation_log.json`
- [ ] Failed propagations logged with full context
- [ ] `audiagentic planning audit` reports inconsistent hierarchies
- [ ] `audiagentic planning audit --fix` repairs inconsistencies
- [ ] Audit tool idempotent (safe to run multiple times)

## AC-9: Performance Acceptable
- [ ] ASYNC mode: state change API returns in <10ms
- [ ] SYNC mode: 50-item hierarchy propagates in <500ms
- [ ] 100-item hierarchy propagates in <5 seconds
- [ ] No memory leaks during 1000 propagation cycles
- [ ] Batched writes reduce disk I/O compared to naive implementation

## AC-10: Error Handling
- [ ] Invalid state transitions are rejected with clear errors
- [ ] Propagation failures are logged but don't crash system
- [ ] Partial failures don't leave items in permanently inconsistent state (audit tool can fix)
- [ ] Subscriber exceptions isolated (one failure doesn't affect others)

## AC-11: Documentation Complete
- [ ] State propagation rules documented with examples
- [ ] Config file schema documented (including SYNC/ASYNC mode)
- [ ] Troubleshooting guide for common propagation issues
- [ ] Migration guide from manual to automatic state management
- [ ] Audit tool usage documented with examples
- [ ] Eventual consistency model explained (when hierarchies may be temporarily inconsistent)
