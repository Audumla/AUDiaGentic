---
id: spec-0046
label: Guidance levels for controlling planning depth-of-detail
state: draft
summary: Specification for orthogonal guidance levels (light/standard/deep) that control
  spec/task required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles
request_refs:
  - request-0029
task_refs: []
standard_refs:
- standard-0009
---


# Purpose

Introduce an orthogonal guidance system that controls the depth, detail, and rigor of planning content independently of work-type profiles (feature/issue/fix/enhancement).

This enables the same workflow (e.g., feature→spec→task) to produce different levels of detail based on implementor skill level or project needs.

# Scope

## In Scope

- Define guidance_levels structure in `profiles.yaml`
- Add `guidance` field to request frontmatter
- Configure different required/suggested sections per guidance level
- Control acceptance criteria depth per guidance level
- Apply guidance levels during request creation and validation

## Out of Scope (v1)

- Hook/automation rules based on guidance
- Event metadata changes for downstream tooling
- Dynamic content generation based on guidance
- Per-user or per-role guidance assignment

# Requirements

## 1. Profile Structure

Add `guidance_levels` section to `.audiagentic/planning/config/profiles.yaml`:

```yaml
planning:
  guidance_levels:
    light:
      description: Basic depth for quick intake or simple tasks
      label: Light (basic)
      defaults:
        meta:
          guidance: light
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
    standard:
      description: Standard depth for typical team workflows
      label: Standard (standard)
      defaults:
        meta:
          guidance: standard
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
    deep:
      description: Deep depth for complex work or rigorous review
      label: Deep (deep)
      defaults:
        meta:
          guidance: deep
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

Add `guidance` field to request frontmatter:

```yaml
---
id: request-XXXX
label: Example request
state: captured
summary: Example
source: manual
guidance: standard  # light, standard, or deep
---
```

## 3. Default Guidance

Configure default guidance in `.audiagentic/planning/config/planning.yaml`:

```yaml
planning:
  default_guidance: standard  # or light, deep
```

## 4. CLI Parameter

Add `--guidance` flag to `tm.py` request creation:

```bash
tm request --profile feature --guidance deep "Add new feature"
```

## 5. Validation Rules

Update validation to enforce guidance-appropriate sections:

- `light`: Warn if spec has excessive detail
- `standard`: Standard validation
- `deep`: Require all required sections, check acceptance criteria depth

## 6. Profile Combination

When creating a request with both `--profile` and `--guidance`:

- `--profile` controls: `on_request_create` cascade, `allow_plan_overlay`
- `--guidance` controls: required sections, acceptance criteria depth, verbosity

Example: `--profile feature --guidance deep` creates request→spec→task with rigorous content.

# Constraints

- **Backward compatible**: No `guidance` field = use `standard` defaults
- **Simple configuration**: All in `profiles.yaml`, no new config files
- **Validation-friendly**: Enforce at validation time, not creation time
- **Extensible**: Future versions can add more guidance levels or hook rules

# Acceptance Criteria

- [ ] `guidance_levels` section added to `profiles.yaml`
- [ ] `guidance` field added to request frontmatter schema
- [ ] Default guidance configurable in `planning.yaml`
- [ ] `--guidance` CLI parameter implemented
- [ ] Validation enforces guidance-appropriate sections
- [ ] Profile combination documented
- [ ] All planning tests pass
- [ ] Backward compatible (no guidance = standard defaults)

# Notes

This is orthogonal to stack-profiles (request-0010). Stack profiles control execution topology (what objects get created). Guidance controls content depth (how detailed the output should be).

They can be combined: `--profile feature --guidance deep` creates a feature workflow with deep, rigorous content.
