<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

---
name: ag-audit
description: Use for canonical @ag-audit launches. Checks tracked docs, release artifacts, and state consistency across the project.
---

# ag-audit skill

Use this skill for canonical `@ag-audit` launches.

Trigger:
- first non-empty line resolves to `ag-audit` or a configured alias (`aga`, `a`, `audit`)

Do:
- audit tracked docs, release artifacts, and state consistency across the project
- check component registry, canonical IDs, schema files, and baseline assets for drift
- note specific drift, missing evidence, stale references, or broken invariants
- verify planning records, job records, and sessions are internally consistent
- produce a scoped, deterministic audit report with prioritized findings

Do not:
- do not mutate tracked docs, code, or planning records without explicit user approval
- do not hide drift behind vague summaries — name the specific files and IDs
- do not broaden audit into implementation work
- do not skip findings because they seem minor — report all drift

Root surface: `.opencode/skills/ag-audit/SKILL.md`
