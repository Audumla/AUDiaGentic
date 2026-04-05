<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

---
name: ag-audit
description: Use for canonical @ag-audit launches. Checks tracked docs, release artifacts, and state consistency.
---

# ag-audit skill

Use this skill for canonical `@ag-audit` launches.

Trigger:
- first non-empty line resolves to `ag-audit` or a configured alias

Do:
- audit tracked docs, release artifacts, and state consistency
- note drift, missing evidence, or stale references
- avoid implementation work unless explicitly asked

Do not:
- do not mutate tracked docs without approval
- do not hide drift behind vague summaries

Root surface: `.agents/skills/ag-audit/SKILL.md`
