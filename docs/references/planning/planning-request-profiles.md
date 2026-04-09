# Planning request profiles

This phase ships two lightweight request profiles:

- `feature`
- `issue`

These are classification/default layers for Requests. They do **not** replace request workflows, profile packs, or execution workflow profiles.

## Purpose

Request profiles help installed projects keep intake simple while still distinguishing between feature-oriented work and issue/problem reports.

## Current phase

In this phase, request profiles are delivered as config + schema + examples and are lightly wired into request creation. They still do not replace request workflows or become a second planning workflow system.

## Example

```yaml
request_profiles:
  feature:
    label: Feature request
    defaults:
      meta:
        request_type: feature
      current_understanding: Initial feature intake captured; desired outcome and implementation boundaries need refinement.
      open_questions:
        - What exact outcome is required?
        - What constraints or non-goals apply?
        - How will success be verified?
    suggested_sections: [Problem, Desired Outcome, Constraints]

  issue:
    label: Issue report
    defaults:
      meta:
        request_type: issue
      current_understanding: Initial issue intake captured; impact and reproduction detail still need confirmation.
      open_questions:
        - What is the observed impact or failure mode?
        - How can this be reproduced or verified?
        - What constraints or non-goals apply?
    suggested_sections: [Problem, Impact, Reproduction, Constraints]
```

## Creation behavior

When a request is created without a profile, the planning layer now seeds a generic intake shape:

- `current_understanding`
- `open_questions`
- `# Understanding`
- `# Source Refs`
- `# Open Questions`
- `# Notes`

When a request is created with a profile such as `feature` or `issue`, the profile can also seed:

- `meta`
- `current_understanding`
- `open_questions`
- extra suggested body sections
