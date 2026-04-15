---
id: standard-0006
label: Planning structure and record quality standard
state: ready
summary: Default standard for how planning work should be structured and what requests,
  specs, plans, work packages, and tasks must contain to be actionable and reviewable.
---

# Standard

Default standard for how planning work in AUDiaGentic-based projects should be structured, and what planning records must contain to be actionable, reviewable, and safe to execute.

# Source Basis

This standard is derived from the repository's planning model and implementation-preparation practice.

Sources:

- Repository planning schemas and workflow conventions
- Project planning tasks, plans, and specifications
- [Shape Up — Basecamp](https://basecamp.com/shapeup) — appetite, scoping, and pitch structure adapted for planning records

# Requirements

1. Every planning record must have a clear label and summary that describe the work in plain language.
2. Requests, specs, plans, work packages, and tasks must be written so a reader can understand scope without reading code first.
3. Planning records must distinguish:

   - in scope
   - out of scope
   - dependencies
   - risks
   - verification expectations

4. Requests should capture the motivation, current understanding, source references, and open questions, rather than acting as implementation instructions.
5. Once a spec exists, the request should stay lightweight and summarize or link rather than restating detailed requirements, acceptance criteria, or execution structure that belong in the spec or plan.
6. Specs must define requirements and constraints clearly enough that implementation can be judged against them.
7. Specs that introduce new components must reference standard-0011 (component architecture) and address layering, modularity, config-driven behavior, and extensibility within their scope.
8. Plans must define sequencing, execution stages, and risk handling.
9. Work packages must group related tasks coherently and state the package objective.
10. A plan may contain multiple work packages when the work naturally splits by execution boundary, ownership, risk, or verification stage.
11. A work package should not exist only as a mirror of the plan title when the plan has no meaningful internal execution split; in that case, either keep one tightly-scoped work package or simplify the planning slice.
12. Tasks must be specific enough that an implementer can identify:

    - files or surfaces likely to change
    - what not to change
    - what verification is expected
    - what done means

13. Plans and work packages should decompose work along real execution seams:

    - setup or scaffolding versus runtime behavior
    - implementation versus migration
    - code changes versus verification and documentation closure
    - independently reviewable or independently ownable slices

14. Planning records must not overstate implementation status. Scaffolding, design, review prep, and completed implementation must be described accurately.
15. Broken or unresolved references must be treated as defects in planning quality.

# Default Rules

- Prefer short, explicit sections over broad narrative prose.
- Keep requests lighter than the downstream spec and plan; avoid duplicating detail across layers.
- Keep acceptance criteria concrete and verifiable.
- Add execution checklists when work would otherwise be easy to misinterpret.
- Keep planning records aligned with actual repository structure and current tooling.
- Prefer splitting work packages by execution reality, not by habit or one-to-one document mirroring.
- Use one work package when the delivery slice is genuinely one tightly-coupled implementation burst.

# Non-Goals

- Enforcing one exact prose template for all planning kinds.
- Replacing architecture documents with task-level detail.
- Turning planning records into long-form design essays.
- Requiring every request, spec, or plan to expand into multiple work packages.
