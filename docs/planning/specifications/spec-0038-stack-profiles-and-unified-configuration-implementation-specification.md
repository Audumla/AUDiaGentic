---
id: spec-0038
label: Stack profiles and unified configuration — Implementation specification
state: done
summary: Specification for the unified profile system enabling lightweight request
  to specification or request to task workflows, optional planning overlay where
  allowed, and source field tracking
request_refs:
- request-0010
task_refs: []
---

# Purpose

Define the implementation contract for the unified planning profile system that combines request defaults with downstream creation topology. The delivered profile model should support lightweight execution by default while preserving optional planning overlay where explicitly allowed.

# Scope

In scope:

- unified `profiles` configuration in `profiles.yaml`
- single `profile` selection driving both request defaults and downstream creation behavior
- lightweight request-to-specification and request-to-task flows
- optional plan and work-package overlay for profiles that permit it
- required `source` field support for request traceability

Out of scope:

- audience-level profile depth and narrative style tuning tracked separately by `request-0009`
- reinstating separate `stack_profile` and `request_profile` APIs
- mandatory plan or work-package creation for all profile-driven requests

# Requirements

## 1. Unified Profile Configuration

- Planning configuration must expose a single `profiles` structure rather than separate request-profile and stack-profile sections.
- Each profile must be able to define request defaults, downstream object creation behavior, and whether planning overlay is permitted.

## 2. Single Profile Parameter

- Request creation and helper surfaces must accept a single `profile` selector.
- The selected profile must apply request defaults and downstream creation topology together.
- Existing behavior without a profile must remain unchanged.

## 3. Lightweight Execution Paths

- The profile model must support request to specification flows for bounded design-led work.
- The profile model must support request to task flows for issue and fix work where direct execution is appropriate.
- Work-package schema rules remain unchanged; overlay stays additive rather than mandatory.

## 4. Optional Planning Overlay

- Profiles that allow overlay must support later application of plan and work-package structure around existing implementation work.
- Overlay must wrap the active work without invalidating existing task relationships.

## 5. Request Traceability

- Requests created through this flow must require `source`.
- Traceability improvements introduced alongside the profile work must remain part of the delivered behavior.

# Constraints

1. Requests without a profile must preserve backward-compatible behavior.
2. Profile terminology must stay aligned with the current shipped model in `profiles.yaml`.
3. Work-package schema requirements must not be weakened to make lightweight execution possible.

# Acceptance Criteria

- [x] A unified `profiles` structure replaces separate request-profile and stack-profile config
- [x] One `profile` parameter controls both request defaults and downstream creation behavior
- [x] Requests without a profile behave as before
- [x] Lightweight request to specification and request to task flows are supported by the shipped profile model
- [x] Optional planning overlay remains available only where configured
- [x] Request `source` is required for traceability
- [x] Linked implementation task(s) are complete
