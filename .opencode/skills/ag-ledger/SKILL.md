<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

---
name: ag-ledger
description: Use for canonical ag-ledger launches. Checks ledger state, tracked docs, release artifacts, and project consistency.
---

# ag-ledger skill

Use this skill for canonical `@ag-ledger` launches.

Trigger:
- first non-empty line resolves to `ag-ledger` or a configured alias (`agl`, `l`, `ledger`)

Do:
- inspect ledger state, tracked docs, release artifacts, and project consistency
- check component registry, canonical IDs, schema files, and baseline assets for drift
- note specific drift, missing evidence, stale references, or broken invariants
- verify planning records, job records, and sessions are internally consistent
- produce a scoped, deterministic ledger report with prioritized findings

Do not:
- do not mutate tracked docs, code, or planning records without explicit user approval
- do not hide drift behind vague summaries — name the specific files and IDs
- do not broaden ledger checks into implementation work
- do not skip findings because they seem minor — report all drift

Root surface: `.opencode/skills/ag-ledger/SKILL.md`
