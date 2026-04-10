---
id: request-0029
label: Add guidance levels (light/standard/deep) to control planning depth-of-detail
state: captured
summary: '"Introduce orthogonal guidance levels (light/standard/deep) that control
  spec/task required sections, detail verbosity, and acceptance criteria depth independently
  of work-type profiles (enhancement/feature/issue/fix)"'
source: claude
current_understanding: Guidance levels (light/standard/deep) control spec/task required
  sections, detail verbosity, and acceptance criteria depth independently of work-type
  profiles. This is a refinement of request-0009 with clearer naming.
open_questions:
- Should guidance be a top-level frontmatter field (like workflow) or stored in meta?
- Should the default guidance be configurable per-project in planning.yaml, or always
  'standard'?
- Which required or suggested sections should differ between light/standard/deep,
  and by how much?
- Should guidance also affect hook/automation rules or event metadata for downstream
  tooling?
context: 'Refinement of request-0009: renamed ''audience profiles'' to ''guidance
  levels'' for clarity'
standard_refs:
- standard-0001
- standard-0009
spec_refs:
  - spec-0046
meta:
  task_refs:
    - task-0236
---


# Understanding

Guidance levels (light/standard/deep) control spec/task required sections, detail verbosity, and acceptance criteria depth independently of work-type profiles. This is a refinement of request-0009 with clearer naming.

# Open Questions

- Should guidance be a top-level frontmatter field (like workflow) or stored in meta?
- Should the default guidance be configurable per-project in planning.yaml, or always 'standard'?
- Which required or suggested sections should differ between light/standard/deep, and by how much?
- Should guidance also affect hook/automation rules or event metadata for downstream tooling?
# Notes
