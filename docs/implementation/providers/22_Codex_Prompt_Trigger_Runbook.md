# Codex prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 Codex prompt-trigger path using the repo-owned wrapper, `AGENTS.md`,
and Codex skills.

## Scope

- Codex CLI
- Codex VS Code surface
- repo-owned wrapper / bridge

## Exposure model

Codex is wrapper-driven. A tagged prompt is recognized on the first non-empty line, normalized
by the repository bridge, and then handed to Codex as an explicit skill-directed request.

## Current repo state

The repo now contains the Codex bridge surface required by this runbook:

- `AGENTS.md`
- `.agents/skills/plan/SKILL.md`
- `.agents/skills/implement/SKILL.md`
- `.agents/skills/review/SKILL.md`
- `.agents/skills/audit/SKILL.md`
- `.agents/skills/check-in-prep/SKILL.md`
- `.agents/skills/adhoc/SKILL.md`
- `tools/codex_prompt_trigger_bridge.py`

## Required assets

- `AGENTS.md`
- `.agents/skills/plan/SKILL.md`
- `.agents/skills/implement/SKILL.md`
- `.agents/skills/review/SKILL.md`
- `.agents/skills/audit/SKILL.md`
- `.agents/skills/check-in-prep/SKILL.md`
- optional `.agents/skills/adhoc/SKILL.md`
- repo-owned wrapper or bridge command

## Smoke tests

- `@plan` reaches the shared launcher
- `@implement` reaches the shared launcher
- `@review` reaches the shared launcher

## Acceptance

- canonical tags are exposed in chat through the wrapper
- Codex-specific instructions stay isolated
- fallback bridge works if wrapper interception is partial

## Related docs

- `docs/specifications/architecture/providers/03_Codex.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-032.md`
- `docs/implementation/providers/12_Codex_Tag_Execution_Implementation.md`
