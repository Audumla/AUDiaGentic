---
id: task-199
label: Unify --profile and --stack-profile into single parameter
state: done
summary: Merge stack_profiles and request_profiles config into unified profiles structure,
  simplifying the CLI API from two parameters to one
spec_ref: spec-6
request_refs:
- request-9
---



# Description

During stack_profiles implementation, we had two separate profile systems:
- `--profile` (request profiles): controlled Understanding, Open Questions, suggested sections
- `--stack-profile` (stack topology): controlled on_request_create behavior and plan/WP availability

This created API friction: users had to remember two different parameters with overlapping names. This task unified them so a single `--profile` parameter handles both concerns.

# Acceptance Criteria

- [x] profiles.yaml has unified `profiles` section (not separate stack_profiles + request_profiles)
- [x] Single `profile_for(name)` accessor in config.py (not separate stack_profile_for)
- [x] api.py.new() takes only `profile` param (not both profile + stack_profile)
- [x] tm.py --profile handles both request defaults and stack topology
- [x] CLI help text clarifies that --profile drives both behaviors
- [x] MCP wrapper compatible (already used single profile parameter)
- [x] All 164 planning tests pass
- [x] Backward compatible: no --profile = existing behavior (no auto-cascade)

# Implementation

Committed in a0391a0:

**Config Changes:**
- Merged `request_profiles` and `stack_profiles` into unified `profiles`
- Each profile now contains:
  - `description` and `label`
  - `defaults` (Understanding, Open Questions, meta)
  - `on_request_create` (stack topology list)
  - `allow_plan_overlay` (planning availability flag)
  - `suggested_sections` (request defaults)

**Code Changes:**
- `config.py`: Renamed `stack_profile_for()` → `profile_for()`, updated to read from `profiles`
- `api.py`: Removed `stack_profile` parameter; `profile` now triggers cascade
- `req_mgr.py`: Updated to load unified profile via `config.profile_for()`
- `tm.py`: Removed `--stack-profile`; `--profile` help updated

**Profiles Shipped:**
- `enhancement`: request defaults + request→specification flow, overlay available
- `feature`: request defaults + request→specification flow, no overlay by default
- `issue`: request defaults + request→task flow, no overlay
- `fix`: request defaults + request→task flow, no overlay

# Notes

This was a refinement discovered during initial implementation. The unification makes the API simpler and more discoverable: one parameter controls both request context and execution topology. The shipped profile names later settled on `enhancement`, `feature`, `issue`, and `fix`.

Pre-implementation feedback: "can profile not be used [instead of stack-profile]?" → Yes, much cleaner this way.
