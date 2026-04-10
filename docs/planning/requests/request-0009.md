---
id: request-0009
label: Add audience-level profile system to control planning depth-of-detail
state: captured
summary: Introduce orthogonal audience profiles (junior/mid/senior) that control spec/task
  required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles (feature/bug/spike/compliance/rfc)
source: legacy-backfill
current_understanding: 'Initial request intake captured: Introduce orthogonal audience
  profiles (junior/mid/senior) that control spec/task required sections, detail verbosity,
  and acceptance criteria depth independently of work-type profiles (feature/bug/spike/compliance/rfc)'
open_questions:
- Should audience profile be a top-level frontmatter field (like workflow) or stored
  in meta?
- Should the default audience be configurable per-project in planning.yaml, or always
  'standard'?
- Which required/suggested sections differ between junior/mid/senior, and by how much?
- Should audience profiles also affect hook/automation rules or event metadata for
  downstream tooling?
meta:
  source_refs:
  - docs/planning/requests/request-0008.md
  - .audiagentic/planning/config/request-profiles.yaml
  - .audiagentic/planning/config/profiles.yaml
  - .audiagentic/planning/config/planning.yaml
  - src/audiagentic/planning/app/api.py
  - tools/planning/tm_helper.py
---




# Understanding

Initial request intake captured: Introduce orthogonal audience profiles (junior/mid/senior) that control spec/task required sections, detail verbosity, and acceptance criteria depth independently of work-type profiles (feature/bug/spike/compliance/rfc)

# Open Questions

- What exact outcome is required?
- What constraints or non-goals apply?
- What follow-up detail is still needed before implementation?
# Notes
