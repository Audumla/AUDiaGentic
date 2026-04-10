---
id: request-0009
label: Add audience-level profile system to control planning depth-of-detail
state: captured
summary: Introduce orthogonal audience profiles (junior/mid/senior) that control spec/task
  required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles (feature/bug/spike/compliance/rfc)
source: legacy-backfill
current_understanding: Introduce orthogonal audience profiles (junior/mid/senior) that control spec/task required sections, detail verbosity, and acceptance criteria depth independently of work-type profiles (feature/issue/fix/enhancement).
open_questions:
  - Should audience profile be a top-level frontmatter field (like workflow) or stored in meta?
  - Should the default audience be configurable per-project in planning.yaml, or always 'standard'?
  - Which required/suggested sections differ between junior/mid/senior, and by how much?
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

Introduce orthogonal audience profiles (junior/mid/senior) that control spec/task required sections, detail verbosity, and acceptance criteria depth independently of work-type profiles (feature/issue/fix/enhancement).

This is distinct from stack-profiles (request-0010) which control execution topology (what objects get created). Audience profiles control content depth (how detailed the output should be).

# Open Questions

- Should audience profile be a top-level frontmatter field (like workflow) or stored in meta?
- Should the default audience be configurable per-project in planning.yaml, or always 'standard'?
- Which required/suggested sections differ between junior/mid/senior, and by how much?
- Should audience profiles also affect hook/automation rules or event metadata for downstream tooling?

# Notes

Request-0010 (stack profiles) handles execution topology. This request handles content depth. They are orthogonal and can be combined.

Example: `profile: feature` + `audience: senior` creates request→spec→task with deep, rigorous content.
