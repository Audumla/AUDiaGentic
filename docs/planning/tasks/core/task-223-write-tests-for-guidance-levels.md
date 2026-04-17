---
id: task-223
label: Write tests for guidance levels
state: done
summary: Add tests for guidance_levels config, guidance field validation, CLI parameter,
  and section enforcement per guidance level
spec_ref: spec-10
request_refs:
- request-11
standard_refs:
- standard-5
- standard-6
---







# Description

Add comprehensive tests for guidance_levels configuration, guidance field validation, CLI parameter, and section enforcement per guidance level.

# Acceptance Criteria

- [ ] Tests for guidance_levels loading from profiles.yaml
- [ ] Tests for default_guidance loading from planning.yaml
- [ ] Tests for guidance field validation in schema
- [ ] Tests for new_request() with guidance parameter
- [ ] Tests for --guidance CLI parameter
- [ ] Tests for validation rules per guidance level
- [ ] Tests for backward compatibility (no guidance)
- [ ] Tests for profile + guidance combination
- [ ] All tests pass
- [ ] Test coverage > 80%

# Notes

This task ensures all guidance level functionality is tested and working correctly.

# State

done
