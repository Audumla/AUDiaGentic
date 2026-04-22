---
id: task-213
label: Add guidance_levels to profiles.yaml
state: done
summary: Add guidance_levels section (light/standard/deep) to .audiagentic/planning/config/profiles.yaml
  with defaults, sections, and acceptance_criteria_depth
spec_ref: spec-13
request_refs:
- request-11
standard_refs:
- standard-5
- standard-6
---













# Description

Add guidance_levels section to `.audiagentic/planning/config/profiles.yaml` with three levels: light, standard, and deep. Each level defines defaults for current_understanding, open_questions, spec_sections, task_sections, and acceptance_criteria_depth.

# Acceptance Criteria

- [ ] guidance_levels section added to profiles.yaml under planning key
- [ ] Three levels defined: light, standard, deep
- [ ] Each level has: description, label, defaults, spec_sections, task_sections, acceptance_criteria_depth
- [ ] light: basic depth, minimal required sections, basic acceptance criteria
- [ ] standard: standard depth, moderate required sections, standard acceptance criteria
- [ ] deep: deep depth, all required sections, rigorous acceptance criteria
- [ ] YAML syntax validated
- [ ] Existing profiles.yaml structure preserved

# Notes

This is the foundation for all other guidance level functionality. All other tasks depend on this being correct.

# State

done
