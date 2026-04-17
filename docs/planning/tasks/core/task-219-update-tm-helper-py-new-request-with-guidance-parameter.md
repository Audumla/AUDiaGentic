---
id: task-219
label: Update tm_helper.py new_request() with guidance parameter
state: done
summary: Add guidance parameter to new_request(), validate against guidance_levels,
  apply guidance defaults to Understanding and Open Questions
spec_ref: spec-10
request_refs:
- request-11
standard_refs:
- standard-5
- standard-6
---







# Description

Add guidance parameter to new_request() function in tm_helper.py. Validate guidance against available guidance_levels and apply guidance-specific defaults to current_understanding and open_questions fields.

# Acceptance Criteria

- [ ] guidance parameter added to new_request() signature
- [ ] Parameter defaults to config.default_guidance
- [ ] Validation against guidance_levels from config
- [ ] Guidance defaults applied to current_understanding
- [ ] Guidance defaults applied to open_questions
- [ ] Guidance field set in meta
- [ ] Error raised for invalid guidance value
- [ ] Tests for new_request() with guidance
- [ ] Backward compatible (no guidance = standard)

# Notes

This task ensures new requests get appropriate defaults based on guidance level.

# State

done
