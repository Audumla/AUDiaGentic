<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

---
name: ag-review
description: Use for canonical @ag-review launches. Performs read-focused validation and completeness review without adding implementation work.
---

# ag-review skill

Use this skill for canonical `@ag-review` launches.

Trigger:
- first non-empty line resolves to `ag-review` or a configured alias

Do:
- perform read-focused validation and completeness review
- identify blockers, missing tests, and contract mismatches
- produce a deterministic review report

Do not:
- do not add implementation work unless explicitly asked
- do not broaden review into feature-scope changes

Root surface: `.opencode/skills/ag-review/SKILL.md`
