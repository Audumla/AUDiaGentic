---
id: spec-2
label: Archive state and functionality specification
state: done
summary: Define archive state workflow, state-based archive behavior, and filtering
  behavior
request_refs:
- request-4
standard_refs:
- standard-6
- standard-5
- standard-9
task_refs: []
---

# Purpose

Move the planning engine from src/audiagentic/planning/app/ to src/audiagentic/foundation/workflow/ as a generic, configurable workflow engine. Planning becomes one configured instance. Other workflows (deployments, CI, etc.) can reuse the same engine.

# Scope

## In Scope
- Create foundation/workflow/ module with generic WorkflowAPI
- Move EventLog, EventService to foundation/workflow/
- Build automation engine that connects automations.yaml to EventBus
- Make Config accept workflow_name parameter
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

Move EventLog and EventService from planning/app/ to foundation/workflow/. They are generic and should not be planning-specific.

## 5. Backward Compatibility

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
4. EventLog, EventService live in foundation/workflow/
5. PlanningAPI is a thin wrapper around WorkflowAPI
6. All existing planning tests pass
7. Import paths updated in v2 MCP server
