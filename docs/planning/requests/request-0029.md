---
id: request-0029
label: Add guidance levels (light/standard/deep) to control planning depth-of-detail
state: captured
summary: Introduce orthogonal guidance levels (light/standard/deep) that control spec/task
  required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles (enhancement/feature/issue/fix)
source: codex
current_understanding: Guidance levels (light/standard/deep) control spec/task required
  sections, detail verbosity, and acceptance criteria depth independently of work-type
  profiles. This is a refinement of request-0009 with clearer terminology — light/standard/deep
  describes content depth rather than audience skill level.
context: Refinement of request-0009 with clearer terminology
open_questions:
- Should guidance be a top-level frontmatter field (like workflow) or stored in meta?
- Should the default guidance be configurable per-project in planning.yaml, or always
  'standard'?
- Which required or suggested sections should differ between light/standard/deep,
  and by how much?
- Should guidance also affect hook/automation rules or event metadata for downstream
  tooling?
standard_refs:
- standard-0001
- standard-0009
spec_refs:
- spec-0046
meta:
  supersedes: request-0009
---

# Understanding

Guidance levels (light/standard/deep) control spec/task required sections, detail verbosity, and acceptance criteria depth independently of work-type profiles (`enhancement`, `feature`, `issue`, `fix`).

This is a refinement of `request-0009` with clearer naming. "Guidance level" describes what it actually controls (how much guidance/detail is required in planning records), whereas "audience profile" was ambiguous about whether it described the writer or reader.

Example: `profile: feature` + `guidance: deep` would create a request→specification flow with rigorous required sections and detailed acceptance criteria, while `profile: fix` + `guidance: light` would keep a request→task flow but allow minimal explanatory content.

# Open Questions

- Should guidance be a top-level frontmatter field (like workflow) or stored in meta?
- Should the default guidance be configurable per-project in planning.yaml, or always 'standard'?
- Which required or suggested sections should differ between light/standard/deep, and by how much?
- Should guidance also affect hook/automation rules or event metadata for downstream tooling?

# Notes

This request should only proceed with a planning-layer impact review across workflow/config, helper/API behavior, MCP exposure, validation, generated surfaces, and automation assumptions, consistent with `standard-0009`.

Supersedes `request-0009` (audience-level profiles) with clearer terminology.
