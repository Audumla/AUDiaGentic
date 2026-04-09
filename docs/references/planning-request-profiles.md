# Planning request profiles

This phase ships two lightweight request profiles:

- `feature`
- `issue`

These are classification/default layers for Requests. They do **not** replace request workflows, profile packs, or execution workflow profiles.

## Purpose

Request profiles help installed projects keep intake simple while still distinguishing between feature-oriented work and issue/problem reports.

## Current phase

In this phase, request profiles are delivered as config + schema + examples. They are intended for validation, scaffolding, and agent guidance. They are not yet deeply wired into the core planning create/update flow.

## Example

```yaml
request_profiles:
  feature:
    label: Feature request
    defaults:
      meta:
        request_type: feature
    suggested_sections: [Problem, Desired Outcome, Constraints]

  issue:
    label: Issue report
    defaults:
      meta:
        request_type: issue
    suggested_sections: [Problem, Impact, Reproduction, Constraints]
```
