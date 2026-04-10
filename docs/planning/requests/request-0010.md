---
id: request-0010
label: Implement configurable stack profiles for lightweight req→spec→task workflows
state: distilled
summary: Implement a unified profile system that controls request defaults and downstream
  creation topology, enabling lightweight request→specification or request→task flows
  with optional planning overlay where appropriate
current_understanding: 'Planning module now uses a unified profile model covering enhancement,
  feature, issue, and fix request types. Profiles combine request defaults with downstream
  creation topology, making lightweight execution first-class while still allowing
  planning overlay where appropriate.'
open_questions: []
source: consolidation
context: Consolidated canonical request for stack-profile and overlay work after reviewing exploratory request records.
meta:
  consolidated_requests:
  - request-0011
  - request-0012
  - request-0013
  - request-0014
  - request-0015
  - request-0016
  outcomes_delivered:
  - Merged request_profiles and stack_profiles into unified `profiles` structure in profiles.yaml
  - Implemented cascade creation in PlanningAPI.new() to auto-create specs when request uses profile
  - Added apply_plan_overlay() method for applying plan/WP mapping over existing spec-linked tasks
  - Unified CLI: single --profile parameter handles both request defaults and stack topology
  - Exposed overlay-plan subcommand for applying plan/WP overlay to existing tasks
  - Made source field required for all requests to track request origin
  - All 164 planning tests pass; backward compatible (no profile = existing behavior)
---

# Understanding

The planning module required a lightweight execution path that doesn't mandate plans and work packages. This request drove the implementation of a unified profile system that combines request defaults with downstream creation topology, so lightweight execution can be the default while fuller planning structure remains available where needed.

The implementation preserves the existing strict schema (work packages still require plans) while making the planning lifecycle genuinely optional at the request level.

Exploratory test requests created during implementation review were consolidated here so the stack-profile feature has a single canonical request record. `request-0009` remains a separate request because it tracks audience-level profile depth/detail rather than stack-topology behavior.

# Open Questions

None at consolidation time.

# Delivery

Implemented across commits c8370e7, a0391a0, bc90445, e9b7b20:

## c8370e7 — Stack Profiles Implementation

- Separate stack-profile behavior to control execution topology
- Auto-cascade: specs auto-created when request uses a profile

## a0391a0 — Unified Profile Refinement

- Merged request_profiles + stack_profiles into single `profiles` structure
- Single `--profile` parameter handles both request defaults and stack topology
- `profile_for()` unified accessor in config.py
- Profiles now contain: defaults (Understanding, meta), on_request_create, allow_plan_overlay

## bc90445 — Task-0215 Documentation

- Tracked the unification as a formal refinement task under spec-0024

## e9b7b20 — Source Field Required

- Made `source` required field on all requests (schema + validation)
- --source now required CLI argument for request creation
- Improves auditability and request traceability

Current profile model:

- `enhancement`: request → specification with optional planning overlay
- `feature`: request → specification without plan overlay by default
- `issue`: request → task with diagnosis-oriented intake defaults
- `fix`: request → task with implementation-oriented intake defaults

Backward compatibility note: requests without profile continue to avoid automatic downstream creation.

# Acceptance Criteria

- [x] Profile-driven downstream creation supports lightweight execution without mandatory plan/WP layers
- [x] Requests without profile behave as before (no automatic downstream creation)
- [x] Tasks only require spec_ref, not plan_ref (already true, codified)
- [x] Plan/WP overlay wraps existing tasks without disruption
- [x] Planning tests passed during delivery
- [x] No schema changes to work-package (plan_ref stays required)

# Notes

Planning layer is now optimized for lightweight execution. Agents can work with request+spec or request+task flows without mandatory planning overhead, and planning structure can be applied declaratively when needed.

Consolidation notes:

- Rolled in exploratory stack-profile requests `request-0011` through `request-0016`
- Re-pointed linked implementation artifacts to `request-0010` for traceability
- Preserved `request-0009` as a separate future-facing request about audience-level profiles
