---
id: plan-007
label: Implement guidance levels for planning depth-of-detail
state: draft
summary: Plan for implementing guidance levels (light/standard/deep) to control spec/task
  depth independently of work-type profiles
spec_refs:
- spec-010
request_refs:
- request-11
work_package_refs: []
standard_refs:
- standard-0006
---




# Objectives

1. Add guidance_levels configuration to profiles.yaml
2. Expose guidance field in request schema and frontmatter
3. Implement guidance parameter in tm_helper.py and tm.py CLI
4. Update validation to enforce guidance-appropriate sections
5. Configure default_guidance in planning.yaml
6. Write comprehensive tests for guidance levels

# Delivery Approach

1. **Configuration layer** (task-0216, task-0222): Add guidance_levels to profiles.yaml and default_guidance to planning.yaml
2. **Schema layer** (task-0218): Update request.schema.json with guidance field
3. **API layer** (task-0217, task-0219): Update Config class and tm_helper.py new_request()
4. **CLI layer** (task-0220): Add --guidance parameter to tm.py
5. **Validation layer** (task-0221): Update val_mgr.py to enforce guidance rules
6. **Tests** (task-0223): Write tests for all layers

# Dependencies

- spec-010: Guidance levels specification
- standard-0005: Config file conventions
- standard-0006: Planning item structure
- standard-0009: Validation rules
