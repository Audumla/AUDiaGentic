---
id: task-222
label: Add default_guidance to planning.yaml
state: done
summary: Add default_guidance field to .audiagentic/planning/config/planning.yaml,
  update Config class to load and provide default
spec_ref: spec-10
request_refs:
- request-11
standard_refs:
- standard-5
- standard-6
---







# Description

Add default_guidance field to `.audiagentic/planning/config/planning.yaml` and update Config class to load and provide default guidance value.

# Acceptance Criteria

- [ ] default_guidance field added to planning.yaml
- [ ] Valid values: light, standard, deep
- [ ] Default value: standard
- [ ] Config class loads default_guidance
- [ ] Config provides default_guidance() method
- [ ] Used when guidance not specified in request
- [ ] Validation for invalid values
- [ ] Tests for default loading
- [ ] Backward compatible (existing files without field)

# Notes

This provides project-level default guidance that can be overridden per-request.

# State

done
