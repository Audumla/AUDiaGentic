---
id: standard-0006
label: Planning record quality standard
state: ready
summary: Default standard for what requests, specs, plans, work packages, and tasks
  must contain to be actionable and reviewable.
---

# Standard

Default standard for what planning records in AUDiaGentic-based projects must contain to be actionable, reviewable, and safe to execute.

# Source Basis

This standard is derived from the repository's planning model and implementation-preparation practice.

Sources:
- repository planning schemas and workflow conventions
- project planning tasks, plans, and specifications

# Requirements

1. Every planning record must have a clear label and summary that describe the work in plain language.
2. Requests, specs, plans, work packages, and tasks must be written so a reader can understand scope without reading code first.
3. Planning records must distinguish:
- in scope
- out of scope
- dependencies
- risks
- verification expectations
4. Specs must define requirements and constraints clearly enough that implementation can be judged against them.
5. Plans must define sequencing, execution stages, and risk handling.
6. Work packages must group related tasks coherently and state the package objective.
7. Tasks must be specific enough that an implementer can identify:
- files or surfaces likely to change
- what not to change
- what verification is expected
- what done means
8. Planning records must not overstate implementation status. Scaffolding, design, review prep, and completed implementation must be described accurately.
9. Broken or unresolved references must be treated as defects in planning quality.

# Default Rules

- Prefer short, explicit sections over broad narrative prose.
- Keep acceptance criteria concrete and verifiable.
- Add execution checklists when work would otherwise be easy to misinterpret.
- Keep planning records aligned with actual repository structure and current tooling.

# Non-Goals

- enforcing one exact prose template for all planning kinds
- replacing architecture documents with task-level detail
- turning planning records into long-form design essays
