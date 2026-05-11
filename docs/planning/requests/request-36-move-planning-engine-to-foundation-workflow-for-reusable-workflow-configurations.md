---
id: request-36
label: Move planning engine to foundation/workflow for reusable workflow configurations
state: captured
summary: Refactor PlanningAPI into generic WorkflowAPI in foundation/workflow so planning
  becomes one configured instance, and other workflows can reuse the same engine with
  their own config and automations.
standard_refs:
- standard-0001
source: agent-session
guidance: standard
context: foundation/workflow refactor
current_understanding: PlanningAPI is hardcoded to planning. Config reads from .audiagentic/planning/config/.
  Event system is in planning/app/ but is generic. automations.yaml exists but is
  dead config - loaded but never executed. EventBus in interoperability is already
  generic.
open_questions:
- Keep PlanningAPI as backward-compat alias?
- Merge planning.yaml + workflows.yaml into workflow.yaml?
- What action types for automation engine?
spec_refs:
- spec-2
- spec-54
- spec-55
plan_refs:
- plan-22
---





# Problem


# Desired Outcome


# Constraints


# Understanding


# Open Questions


# Notes
