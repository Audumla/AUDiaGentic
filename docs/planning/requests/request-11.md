---
id: request-11
label: Add guidance levels (light/standard/deep) to control planning depth-of-detail
state: closed
summary: Introduce orthogonal guidance levels (light/standard/deep) that control spec/task
  required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles (enhancement/feature/issue/fix)
source: codex
current_understanding: Guidance levels (light/standard/deep) control spec/task required
  sections, detail verbosity, and acceptance criteria depth independently of work-type
  profiles. Guidance is a top-level frontmatter field, configurable per-project in
  planning.yaml (default standard). All three levels differ in required/suggested
  sections. In v1, guidance only affects validation — not templates, hooks, or automation.
context: Refinement of request-0009 with clearer terminology
open_questions:
- Which sections should be required at each guidance level?
- Should guidance affect automation or only validation?
standard_refs:
- standard-0001
- standard-0009
spec_refs:
- spec-010
meta:
  supersedes: request-0009
---



# request-11

## Understanding

Guidance levels (light/standard/deep) control spec/task required sections, detail verbosity, and acceptance criteria depth independently of work-type profiles (`enhancement`, `feature`, `issue`, `fix`).

This is a refinement of `request-8` with clearer naming. "Guidance level" describes what it actually controls (how much guidance/detail is required in planning records), whereas "audience profile" was ambiguous about whether it described the writer or reader.

Example: `profile: feature` + `guidance: deep` would create a request→specification flow with rigorous required sections and detailed acceptance criteria, while `profile: fix` + `guidance: light` would keep a request→task flow but allow minimal explanatory content.

## Decisions

### Q1: Top-level field vs meta?

**Decision**: Top-level field (`guidance: standard`)

**Rationale**:

- Consistency: `workflow` is a top-level field, and guidance is equally important
- Validation: Easier to validate at schema level when it's top-level
- CLI: `--guidance` flag maps directly to top-level field
- Readability: More visible in frontmatter, easier to spot

### Q2: Configurable default?

**Decision**: Yes, configurable in `planning.yaml`

**Rationale**:

- Project variation: Different projects need different defaults
- Override capability: Per-request `--guidance` can override project default
- Backward compatible: Existing projects without `default_guidance` use `standard`

**Implementation**:

```yaml
# .audiagentic/planning/config/planning.yaml
planning:
  default_guidance: standard  # or light, deep
```

**Behavior**:

- If `--guidance` specified → use that
- If no `--guidance` → use `default_guidance` from config
- If no config → use `standard`

### Q3: Which sections differ?

**Decision**: All three levels differ in required/suggested sections and acceptance criteria depth

**Light Guidance (basic depth)**:

- Spec sections: Required: `Purpose`, `Scope`, `Requirements`; Suggested: `Constraints`, `Acceptance Criteria`
- Task sections: Required: `Description`; Suggested: `Acceptance Criteria`, `Notes`
- Acceptance criteria depth: Basic (1-2 bullet points per requirement)
- Use case: Quick tasks, simple fixes, internal tools

**Standard Guidance (moderate depth)**:

- Spec sections: Required: `Purpose`, `Scope`, `Requirements`, `Constraints`; Suggested: `Acceptance Criteria`, `Non-Goals`
- Task sections: Required: `Description`, `Acceptance Criteria`; Suggested: `Notes`, `Implementation Notes`
- Acceptance criteria depth: Standard (detailed, testable criteria)
- Use case: Typical feature work, user-facing changes

**Deep Guidance (rigorous depth)**:

- Spec sections: Required: `Purpose`, `Scope`, `Requirements`, `Constraints`, `Acceptance Criteria`; Suggested: `Non-Goals`, `Compatibility`, `Performance Considerations`
- Task sections: Required: `Description`, `Acceptance Criteria`, `Implementation Notes`; Suggested: `Testing Strategy`, `Risk Analysis`
- Acceptance criteria depth: Rigorous (comprehensive, edge cases covered)
- Use case: Complex systems, public APIs, critical infrastructure

### Q4: Affects automation?

**Decision**: No, only validation (v1)

**Rationale**:

- Keep it simple: Automation complexity grows exponentially
- Validation is enough: Ensures content depth matches expectations
- Future extensibility: Can add automation rules later if needed

**What automation is excluded (v1)**:

- No different templates per guidance level
- No different hook behavior per guidance
- No different event metadata per guidance
- No different downstream processing per guidance

**What automation is included (v1)**:

- Validation rules enforce required sections
- Validation warns about excessive/minimal detail

**Future (v2)**:

- Could add guidance-specific templates
- Could add guidance-aware hooks
- Could add guidance-based routing

## Open Questions

- Which sections should be required at each guidance level?
- Should guidance affect automation or only validation?

## Notes

This request should only proceed with a planning-layer impact review across workflow/config, helper/API behavior, MCP exposure, validation, generated surfaces, and automation assumptions, consistent with `standard-0009`.

Supersedes `request-8` (audience-level profiles) with clearer terminology.
