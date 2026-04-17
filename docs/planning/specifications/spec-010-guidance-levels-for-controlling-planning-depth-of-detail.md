---
id: spec-010
label: Guidance levels for controlling planning depth-of-detail
state: draft
summary: Specification for orthogonal guidance levels (light/standard/deep) that control
  spec/task required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles
request_refs:
- request-11
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

# Decisions (from request-11)

## Q1: Top-level field vs meta?
**Decision**: Top-level field (`guidance: standard`)

## Q2: Configurable default?
**Decision**: Yes, configurable in `planning.yaml`

## Q3: Which sections differ?
**Decision**: All three levels differ in required/suggested sections and acceptance criteria depth

## Q4: Affects automation?
**Decision**: No, only validation (v1)

## Q5: Where is guidance stored?
**Decision**: Set once at request level, inherited by all downstream docs

**Rationale**:
- Single source of truth: Request is the root of all planning docs
- No duplication: Specs and tasks don't need their own guidance field
- Automatic inheritance: All downstream docs use the request's guidance
- Simpler schema: Only request needs guidance field

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

Add `guidance` field to **request** frontmatter only (top-level, not in meta):

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

**Inheritance**:
- Specs inherit guidance from their request_refs
- Tasks inherit guidance from their request_refs (or spec's request)
- No guidance field needed in spec/task frontmatter

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

Update validation to enforce guidance-appropriate sections based on the **request's guidance level**:

**Light guidance**:
- Warn if spec has excessive detail (e.g., too many sections)
- Accept minimal required sections
- Basic acceptance criteria (1-2 bullets per requirement)

**Standard guidance**:
- Standard validation
- All required sections present
- Detailed, testable acceptance criteria

**Deep guidance**:
- Require all required sections
- Check acceptance criteria depth (comprehensive, edge cases covered)
- Validate implementation notes and risk analysis

**Validation behavior**:
- Missing required sections → error
- Missing suggested sections → warning
- Excessive detail for light → warning
- Minimal detail for deep → warning

**Inheritance**:
- Validation uses the request's guidance level
- All downstream docs (specs, tasks) validated against same guidance level

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

- [ ] `guidance_levels` section added to `profiles.yaml` with light/standard/deep
- [ ] `guidance` field added to request frontmatter schema (top-level only)
- [ ] Default guidance configurable in `planning.yaml`
- [ ] `--guidance` CLI parameter implemented
- [ ] Validation enforces guidance-appropriate sections
- [ ] Profile combination documented
- [ ] All planning tests pass
- [ ] Backward compatible (no guidance = standard defaults)
- [ ] Light guidance: basic sections, basic acceptance criteria
- [ ] Standard guidance: moderate sections, standard acceptance criteria
- [ ] Deep guidance: all sections, rigorous acceptance criteria
- [ ] Validation warns about excessive/minimal detail
- [ ] Guidance inherited from request to all downstream docs

# Notes

This is orthogonal to stack-profiles (request-9). Stack profiles control execution topology (what objects get created). Guidance controls content depth (how detailed the output should be).

They can be combined: `--profile feature --guidance deep` creates a feature workflow with deep, rigorous content.

**Inheritance model**:
- Guidance set once at request level
- All downstream docs (specs, tasks, plans) inherit from request
- No duplication: Each doc doesn't need its own guidance field
- Single source of truth: Request is the root

**Automation (v1)**:
- Excluded: No different templates, hooks, or event metadata per guidance
- Included: Validation rules enforce required sections and depth
- Future (v2): Could add guidance-specific templates and hooks
