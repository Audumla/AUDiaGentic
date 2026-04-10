---
id: request-0009
label: Add audience-level profile system to control planning depth-of-detail
state: captured
summary: Introduce orthogonal audience profiles (junior/mid/senior) that control spec/task
  required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles (enhancement/feature/issue/fix)
source: legacy-backfill
current_understanding: Audience profiles remain a future-facing planning-layer enhancement. The shipped unified profile model now covers work-type and downstream-creation behavior through enhancement, feature, issue, and fix profiles. This request stays separate because it would add an orthogonal content-depth control that changes planning defaults, validation expectations, and possibly automation behavior without changing the core request-to-specification or request-to-task topology.
open_questions:
  - Should audience profile be a top-level frontmatter field (like workflow) or stored in meta?
  - Should the default audience be configurable per-project in planning.yaml, or always 'standard'?
  - Which required or suggested sections should differ between junior/mid/senior, and by how much?
  - Should audience profiles also affect hook/automation rules or event metadata for downstream tooling?
standard_refs:
  - standard-0009  # Planning layer enhancement impact
meta:
  source_refs:
  - docs/planning/requests/request-0008.md
  - .audiagentic/planning/config/profiles.yaml
  - .audiagentic/planning/config/planning.yaml
  - src/audiagentic/planning/app/api.py
  - tools/planning/tm_helper.py
---




# Understanding

Introduce orthogonal audience profiles (junior/mid/senior) that control spec and task required sections, detail verbosity, and acceptance criteria depth independently of the shipped work-type profiles (`enhancement`, `feature`, `issue`, `fix`).

This is distinct from `request-0010`, which closed the unified work-type profile and downstream-topology changes. That request controls execution topology and request defaults; this request is about whether planning records should also support a separate audience/content-depth dimension.

# Open Questions

- Should audience profile be a top-level frontmatter field (like workflow) or stored in meta?
- Should the default audience be configurable per-project in planning.yaml, or always 'standard'?
- Which required or suggested sections should differ between junior/mid/senior, and by how much?
- Should audience profiles also affect hook/automation rules or event metadata for downstream tooling?

# Notes

`request-0010` handles the now-shipped unified work-type profile system and downstream creation behavior. This request intentionally remains separate because it would affect planning-layer content expectations rather than object topology.

This request should only proceed with a planning-layer impact review across workflow/config, helper/API behavior, MCP exposure, validation, generated surfaces, and automation assumptions, consistent with `standard-0009`.

Example: `profile: feature` + `audience: senior` would create a request→specification flow with more rigorous required sections and acceptance detail, while `profile: fix` + `audience: junior` would keep a request→task flow but allow lighter explanatory content.
