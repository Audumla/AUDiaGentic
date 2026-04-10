---
id: request-0010
label: Implement configurable stack profiles for lightweight req→spec→task workflows
state: distilled
summary: Enable optional plans/work packages via stack_profiles, allowing request→specification→task execution without mandatory plan/WP layers
current_understanding: 'Planning module now supports two configurable stack profiles: direct (req→spec→task only) and full (same base with optional plan/WP overlay). This makes the base planning workflow lightweight while keeping planning structure available when needed.'
open_questions: []
meta:
  outcomes_delivered:
  - Added `direct` and `full` stack profiles to profiles.yaml with configurable on_request_create behavior
  - Implemented cascade creation in PlanningAPI.new() to auto-create specs when request uses stack_profile
  - Added apply_plan_overlay() method for applying plan/WP mapping over existing spec-linked tasks
  - Exposed CLI support via --stack-profile flag and overlay-plan subcommand in tm.py
  - All 162 existing planning tests pass; backward compatible (no profile = existing behavior)
---

# Understanding

The planning module required a lightweight execution path that doesn't mandate plans and work packages. This request drove the implementation of configurable stack profiles that make the base graph (request → specification → task) a first-class workflow, with planning (plan/WP) as an optional overlay applied later when needed.

The implementation preserves the existing strict schema (work packages still require plans) while making the planning lifecycle genuinely optional at the request level.

# Delivery

Implemented in commit c8370e7:

- `stack_profiles` now driven by runtime code, not just config decoration
- Two profiles: `direct` (spec-task only) and `full` (same base, allows overlay)
- Auto-cascade on request creation respects profile configuration
- Plan/WP overlay commands allow later application without re-anchoring tasks
- Full backward compatibility: requests without profile behave exactly as before

# Acceptance Criteria

- [x] Requests with `--stack-profile direct` auto-create spec without plan/WP
- [x] Requests without stack_profile behave as before (no change)
- [x] Tasks only require spec_ref, not plan_ref (already true, codified)
- [x] Plan/WP overlay wraps existing tasks without disruption
- [x] All 162 planning tests pass
- [x] No schema changes to work-package (plan_ref stays required)

# Notes

Planning layer is now optimized for lightweight execution. Agents can work with spec+task flows without planning overhead, and planning structure can be applied declaratively when needed.
