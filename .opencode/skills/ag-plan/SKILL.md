<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

---
name: ag-plan
description: Use for canonical @ag-plan launches. Shapes work into a concrete, scoped execution plan before any implementation starts.
---

# ag-plan skill

Use this skill for canonical `@ag-plan` launches.

Trigger:
- first non-empty line resolves to `ag-plan` or a configured alias (`agp`, `p`, `plan`)

Do:
- map the requested change into a concrete execution plan with discrete steps
- identify dependencies, blockers, risks, and review checkpoints
- verify the target subject exists and is consistent with planning records if an id is supplied
- keep the plan deterministic, scoped, and concise — no implementation work
- surface any ambiguity before committing to a plan shape

Do not:
- do not implement the requested change
- do not create planning items (requests, specs, plans, tasks) without explicit user approval
- do not mutate tracked docs or code without approval
- do not broaden scope beyond what the prompt specifies

Root surface: `.opencode/skills/ag-plan/SKILL.md`
