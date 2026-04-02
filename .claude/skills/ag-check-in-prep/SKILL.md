---
name: ag-check-in-prep
description: Use for canonical @ag-check-in-prep launches. Prepares the repository for a stable check-in.
---

# ag-check-in-prep skill

Use this skill for canonical `@ag-check-in-prep` launches.

Trigger:
- first non-empty line resolves to `ag-check-in-prep` or the backward-compatible `check-in-prep` alias

Do:
- prepare the repo for a stable check-in
- summarize outstanding changes and verification state
- keep the output concise and action-oriented

Do not:
- do not change implementation behavior
- do not broaden into feature work

Root surface: `.claude/skills/ag-check-in-prep/SKILL.md`
