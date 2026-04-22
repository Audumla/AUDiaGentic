---
id: task-249
label: Create state propagation config system
state: done
summary: Implement state_propagation.yaml config with default rules and workflow overrides
spec_ref: spec-24
request_refs:
- request-18
standard_refs:
- standard-5
- standard-6
---












# Description

Create configuration surface for planning state propagation. This task owns loading default propagation behavior, supporting workflow-specific overrides, and exposing on/off control for rollout and debugging.

**Config file:** `.audiagentic/planning/config/state_propagation.yaml`

**Default rules:**
```yaml
enabled: true
mode: ASYNC  # SYNC or ASYNC
max_depth: 10
log_file: planning/meta/propagation_log.json
defaults:
  task:
    to_in_progress: trigger_wp_in_progress
    to_done: check_all_tasks_done_for_wp
    to_blocked: trigger_wp_blocked
  wp:
    to_in_progress: trigger_plan_in_progress
    to_done: check_all_wps_done_for_plan
    to_blocked: trigger_plan_blocked
  plan:
    to_in_progress: trigger_spec_in_progress
    to_done: check_all_plans_done_for_spec
    to_blocked: trigger_spec_blocked
workflows:
  custom_workflow:
    overrides:
      # workflow-specific rules
```

**Key behaviors:**
- Default rules applied if config file missing
- `enabled: false` disables all propagation globally
- `mode: ASYNC` recommended for eventual consistency
- `max_depth: 10` prevents infinite loops
- Workflow-specific overrides supported
- Invalid config fails with clear error message

# Acceptance Criteria

- Default propagation works without explicit config file
- Config file loaded from `.audiagentic/planning/config/state_propagation.yaml`
- `enabled: false` disables all propagation globally
- Workflow-specific overrides loaded and applied
- Invalid config fails with clear error message
- Unit tests cover: defaults, overrides, disablement, invalid config
- Smoke test proves planning config loads with/without propagation settings

# Notes

Propagation engine (task-0251) consumes this config. This task is config loading only.
