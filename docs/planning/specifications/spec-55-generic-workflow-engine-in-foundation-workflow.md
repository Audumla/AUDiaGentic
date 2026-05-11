---
id: spec-55
label: Generic workflow engine in foundation/workflow
state: draft
summary: Refactor planning/app into foundation/workflow with configurable workflow
  instances, working automation engine, and per-workflow config.
request_refs:
- request-36
standard_refs:
- standard-0006
- standard-0005
plan_refs:
- plan-22
---







# Purpose


# Scope


# Requirements


# Constraints


# Acceptance Criteria

# Purpose

Move the planning engine from src/audiagentic/planning/app/ to src/audiagentic/foundation/event/ as a generic, configurable workflow engine. Planning becomes one configured instance. Other workflows (deployments, CI, etc.) can reuse the same engine.

# Scope

## In Scope
- Create foundation/event/ module with generic WorkflowAPI
- Move EventLog, EventService to foundation/event/
- Build automation engine that connects automations.yaml to EventBus
- Make Config accept workflow_name parameter
- Consolidate counter management into single config-driven counters file
- Keep PlanningAPI as backward-compat wrapper
- Per-workflow config directories (.audiagentic/<workflow>/config/)

## Out of Scope
- Changing the planning config structure (planning.yaml, workflows.yaml stay as-is for now)
- Creating new workflow instances (deployments, etc.) - that comes after
- MCP server changes beyond updating import paths

# Requirements

## 1. Generic WorkflowAPI

WorkflowAPI.__init__ accepts:
- root: Path - project root
- workflow: str - workflow name (directory under .audiagentic/)
- test_mode: bool - test mode flag

## 2. Configurable Config

Config class reads from `.audiagentic/<workflow>/config/` instead of hardcoded `.audiagentic/planning/config/`.

## 3. Working Automation Engine

The automation engine reads automations.yaml and subscribes to EventBus events. When an event matches an automation rule, the configured actions execute.

Action types (initial):
- `emit_event` - emit an event to EventBus
- `validate` - run validation on the item
- `note_stub`, `review_stub`, `report_stub` - logging actions
- `subprocess` - run a subprocess command (future)
- `webhook` - call a webhook URL (future)

## 4. Event System in Foundation

Move EventLog and EventService from planning/app/ to foundation/event/. They are generic and should not be planning-specific.

## 5. Configurable Counter Management

Counter management moves from core to config. Each workflow defines its own counter scheme.

Current (hardcoded in core):
- Separate counter files per kind: `requests.json`, `specs.json`, `tasks.json`
- Core code knows about these files

Target (config-driven, per workflow):
- Single counters file: `meta/counters.json` with all kind counters
- Counter file location and structure defined in workflow config

```yaml
# workflow config
counters:
  file: meta/counters.json
```

```json
// counters.json
{
  "request": 36,
  "spec": 53,
  "plan": 21,
  "task": 8,
  "wp": 3,
  "standard": 16
}
```

## 6. Backward Compatibility

PlanningAPI remains as a thin wrapper around WorkflowAPI.

# Constraints

- Each workflow instance has its own automations config - not a singular config
- EventBus stays in audiagentic.interoperability (already generic)
- The automation engine is generic, the config is per-workflow
- Existing planning tests must continue to pass

# Acceptance Criteria

1. WorkflowAPI(root, workflow="planning") works identically to current PlanningAPI(root)
2. Config reads from .audiagentic/<workflow>/config/ based on workflow name
3. Automation engine executes actions from automations.yaml when events fire
4. EventLog, EventService live in foundation/event/
5. Counter management is config-driven, not hardcoded in core
6. PlanningAPI is a thin wrapper around WorkflowAPI
7. All existing planning tests pass
8. Import paths updated in v2 MCP server

# Purpose

Move the planning engine from src/audiagentic/planning/app/ to src/audiagentic/foundation/event/ as a generic, configurable workflow engine. Planning becomes one configured instance. Other workflows (deployments, CI, etc.) can reuse the same engine.

# Scope

## In Scope
- Create foundation/event/ module with generic WorkflowAPI
- Move EventLog, EventService to foundation/event/
- Build automation engine that connects automations.yaml to EventBus
- Make Config accept workflow_name parameter
- Consolidate counter management into single config-driven counters file
- Keep PlanningAPI as backward-compat wrapper
- Per-workflow config directories (.audiagentic/<workflow>/config/)

## Out of Scope
- Changing the planning config structure (planning.yaml, workflows.yaml stay as-is for now)
- Creating new workflow instances (deployments, etc.) - that comes after
- MCP server changes beyond updating import paths

# Requirements

## 1. Generic WorkflowAPI

WorkflowAPI.__init__ accepts:
- root: Path - project root
- workflow: str - workflow name (directory under .audiagentic/)
- test_mode: bool - test mode flag

## 2. Configurable Config

Config class reads from `.audiagentic/<workflow>/config/` instead of hardcoded `.audiagentic/planning/config/`.

## 3. Working Automation Engine

The automation engine reads automations.yaml and subscribes to EventBus events. When an event matches an automation rule, the configured actions execute.

Action types (initial):
- `emit_event` - emit an event to EventBus
- `validate` - run validation on the item
- `note_stub`, `review_stub`, `report_stub` - logging actions
- `subprocess` - run a subprocess command (future)
- `webhook` - call a webhook URL (future)

## 4. Event System in Foundation

Move EventLog and EventService from planning/app/ to foundation/event/. They are generic and should not be planning-specific.

## 5. Configurable Counter Management

Counter management moves from core to config. Each workflow defines its own counter scheme.

Current (hardcoded in core):
- Separate counter files per kind: `requests.json`, `specs.json`, `tasks.json`
- Core code knows about these files

Target (config-driven, per workflow):
- Single counters file: `meta/counters.json` with all kind counters
- Counter file location and structure defined in workflow config

```yaml
# workflow config
counters:
  file: meta/counters.json
```

```json
// counters.json
{
  "request": 36,
  "spec": 53,
  "plan": 21,
  "task": 8,
  "wp": 3,
  "standard": 16
}
```

## 6. Backward Compatibility

PlanningAPI remains as a thin wrapper around WorkflowAPI.

# Constraints

- Each workflow instance has its own automations config - not a singular config
- EventBus stays in audiagentic.interoperability (already generic)
- The automation engine is generic, the config is per-workflow
- Existing planning tests must continue to pass

# Acceptance Criteria

1. WorkflowAPI(root, workflow="planning") works identically to current PlanningAPI(root)
2. Config reads from .audiagentic/<workflow>/config/ based on workflow name
3. Automation engine executes actions from automations.yaml when events fire
4. EventLog, EventService live in foundation/event/
5. Counter management is config-driven, not hardcoded in core
6. PlanningAPI is a thin wrapper around WorkflowAPI
7. All existing planning tests pass
8. Import paths updated in v2 MCP server
