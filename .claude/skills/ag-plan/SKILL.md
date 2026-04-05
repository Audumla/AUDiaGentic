<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

---
name: ag-plan
description: Use for canonical @ag-plan launches. Shapes work before implementation.
---

# ag-plan skill

Use this skill for canonical `@ag-plan` launches.

Trigger:
- first non-empty line resolves to `ag-plan` or a configured alias

Do:
- map the requested change into a concrete execution plan
- identify dependencies, blockers, and review checkpoints
- keep the result deterministic and concise

Do not:
- do not implement the requested change
- do not mutate tracked docs without approval

Root surface: `.claude/skills/ag-plan/SKILL.md`
