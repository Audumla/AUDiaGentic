---
id: wp-9
label: Implement guidance levels in config, API, and validation
state: draft
summary: Add guidance_levels to profiles.yaml, implement guidance field in requests,
  update validation and CLI
plan_ref: plan-11
task_refs:
- ref: task-234
  seq: 1999
- ref: task-235
  seq: 2999
- ref: task-236
  seq: 3999
- ref: task-237
  seq: 4999
- ref: task-238
  seq: 5999
- ref: task-239
  seq: 6999
- ref: task-240
  seq: 7999
- ref: task-241
  seq: 8999
standard_refs:
- standard-6
---











# Objective

Implement guidance levels (light/standard/deep) as an orthogonal dimension to work-type profiles for controlling planning depth-of-detail.

# Scope of This Package

- Add guidance_levels to profiles.yaml
- Add guidance field to request schema
- Update Config class to load guidance configuration
- Add guidance parameter to tm_helper.py new_request()
- Add --guidance CLI parameter to tm.py
- Update validation rules in val_mgr.py
- Add default_guidance to planning.yaml
- Write tests for all guidance level functionality

# Inputs

- spec-10: Guidance levels specification
- profiles.yaml: Current profile configuration
- request.schema.json: Current request schema
- config.py: Current Config class
- tm_helper.py: Current helper functions
- tm.py: Current CLI implementation
- val_mgr.py: Current validation manager
- planning.yaml: Current planning configuration

# Instructions

1. **Define guidance_levels** in profiles.yaml with light/standard/deep levels
2. **Update request.schema.json** to include optional guidance field
3. **Update Config class** to load guidance_levels and default_guidance
4. **Update new_request()** in tm_helper.py to accept guidance parameter
5. **Add --guidance argument** to tm.py request command
6. **Update validation** in val_mgr.py to enforce guidance-appropriate sections
7. **Add default_guidance** to planning.yaml
8. **Write tests** covering all guidance level scenarios

# Required Outputs

- profiles.yaml with guidance_levels section
- request.schema.json with guidance field
- config.py with guidance accessor
- tm_helper.py with guidance parameter
- tm.py with --guidance CLI flag
- val_mgr.py with guidance validation
- planning.yaml with default_guidance
- Test coverage for guidance levels

# Acceptance Checks

- [ ] All 8 tasks (task-0216 through task-0223) completed
- [ ] Guidance levels load correctly from profiles.yaml
- [ ] Guidance field validates against light/standard/deep
- [ ] Default guidance applies when not specified
- [ ] CLI --guidance parameter works correctly
- [ ] Validation enforces guidance-appropriate sections
- [ ] All tests pass
- [ ] Backward compatible (no guidance = standard defaults)

# Non-Goals

- Hook/automation rules based on guidance
- Event metadata changes for downstream tooling
- Dynamic content generation based on guidance
- Per-user or per-role guidance assignment
