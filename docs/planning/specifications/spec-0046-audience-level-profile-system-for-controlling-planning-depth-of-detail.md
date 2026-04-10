---
id: spec-0046
label: Audience-level profile system for controlling planning depth-of-detail
state: draft
summary: Specification for orthogonal audience profiles (junior/mid/senior) that control
  spec/task required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles
request_refs:
  - request-0009
task_refs: []
standard_refs:
  - standard-0009
---

# Purpose

Introduce an orthogonal audience profile system that controls the depth, detail, and rigor of planning content independently of work-type profiles (feature/issue/fix/enhancement).

This enables the same workflow (e.g., feature→spec→task) to produce different levels of detail based on team maturity, reviewer expectations, or project needs.

# Scope

## In Scope

- Define audience profile structure in `profiles.yaml`
- Add `audience` field to request frontmatter
- Configure different required/suggested sections per audience level
- Control acceptance criteria depth per audience level
- Apply audience profiles during request creation and validation

## Out of Scope (v1)

- Hook/automation rules based on audience
- Event metadata changes for downstream tooling
- Dynamic content generation based on audience
- Per-user or per-role audience assignment

# Requirements

## 1. Profile Structure

Add `audience_profiles` section to `.audiagentic/planning/config/profiles.yaml`:

```yaml
planning:
  audience_profiles:
    junior:
      description: Basic depth for junior team members or quick intake
      label: Junior (basic)
      defaults:
        meta:
          audience: junior
        current_understanding: Initial intake captured; key details need refinement.
        open_questions:
          - What is the core requirement?
          - What are the main constraints?
          - How will success be verified?
      spec_sections:
        required: [Purpose, Scope, Requirements]
        suggested: [Constraints, Acceptance Criteria]
      task_sections:
        required: [Description]
        suggested: [Acceptance Criteria, Notes]
      acceptance_criteria_depth: basic
    mid:
      description: Standard depth for typical team workflows
      label: Mid (standard)
      defaults:
        meta:
          audience: mid
        current_understanding: Initial intake captured; requirements are understood well enough to proceed.
        open_questions:
          - What exact outcome is required?
          - What constraints or non-goals apply?
          - How will success be verified?
      spec_sections:
        required: [Purpose, Scope, Requirements, Constraints]
        suggested: [Acceptance Criteria]
      task_sections:
        required: [Description]
        suggested: [Acceptance Criteria, Notes]
      acceptance_criteria_depth: standard
    senior:
      description: Deep depth for complex work or rigorous review
      label: Senior (deep)
      defaults:
        meta:
          audience: senior
        current_understanding: Initial intake captured; requirements are well-understood with clear implementation path.
        open_questions:
          - What exact outcome is required?
          - What constraints or non-goals apply?
          - How will success be verified?
          - What are the implementation risks?
      spec_sections:
        required: [Purpose, Scope, Requirements, Constraints, Acceptance Criteria]
        suggested: [Non-Goals, Compatibility]
      task_sections:
        required: [Description, Acceptance Criteria]
        suggested: [Notes, Implementation Notes]
      acceptance_criteria_depth: rigorous
```

## 2. Frontmatter Field

Add `audience` field to request frontmatter:

```yaml
---
id: request-XXXX
label: Example request
state: captured
summary: Example
source: manual
audience: mid  # junior, mid, or senior
---
```

## 3. Default Audience

Configure default audience in `.audiagentic/planning/config/planning.yaml`:

```yaml
planning:
  default_audience: mid  # or junior, senior
```

## 4. CLI Parameter

Add `--audience` flag to `tm.py` request creation:

```bash
tm request --profile feature --audience senior "Add new feature"
```

## 5. Validation Rules

Update validation to enforce audience-appropriate sections:

- `junior`: Warn if spec has excessive detail
- `mid`: Standard validation
- `senior`: Require all required sections, check acceptance criteria depth

## 6. Profile Combination

When creating a request with both `--profile` and `--audience`:

- `--profile` controls: `on_request_create` cascade, `allow_plan_overlay`
- `--audience` controls: required sections, acceptance criteria depth, verbosity

Example: `--profile feature --audience senior` creates request→spec→task with rigorous content.

# Constraints

- **Backward compatible**: No `audience` field = use `mid` defaults
- **Simple configuration**: All in `profiles.yaml`, no new config files
- **Validation-friendly**: Enforce at validation time, not creation time
- **Extensible**: Future versions can add more audience levels or hook rules

# Acceptance Criteria

- [ ] `audience_profiles` section added to `profiles.yaml`
- [ ] `audience` field added to request frontmatter schema
- [ ] Default audience configurable in `planning.yaml`
- [ ] `--audience` CLI parameter implemented
- [ ] Validation enforces audience-appropriate sections
- [ ] Profile combination documented
- [ ] All planning tests pass
- [ ] Backward compatible (no audience = mid defaults)

# Notes

This is orthogonal to stack-profiles (request-0010). Stack profiles control execution topology (what objects get created). Audience profiles control content depth (how detailed the output should be).

They can be combined: `--profile feature --audience senior` creates a feature workflow with deep, rigorous content.
