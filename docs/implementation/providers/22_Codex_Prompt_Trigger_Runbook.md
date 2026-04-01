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

This is the reference prompt-calling path for the repo:
- first-line canonical tag
- repo-owned bridge
- `AGENTS.md` doctrine
- skill-directed execution
- shared `prompt-launch` handoff

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

## Codex preflight contract

Before the bridge launches a job, the Codex prompt surface must verify that the project
contains:

- `AGENTS.md`
- the five canonical skill files

If any of those assets are missing, the bridge should fail fast with a validation error
instead of pretending the prompt-calling path is ready. That keeps the Codex path testable
and prevents the prompt-calling spec from drifting away from the actual repo state.

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
- `@audit` and `@check-in-prep` resolve through the same Codex bridge path
- missing required Codex assets return a validation error before launch

## Acceptance

- canonical tags are exposed in chat through the wrapper
- Codex-specific instructions stay isolated
- fallback bridge works if wrapper interception is partial
- the bridge validates `AGENTS.md` and the canonical skill files before launch

## Live stream expectations (Phase 4.9)

Codex is a first-wave candidate for live console and runtime progress capture.

For the first pass:
- AUDiaGentic should own stdout/stderr capture and normalized stream persistence
- the Codex wrapper should tee live progress to the console when streaming is enabled
- the provider should not be responsible for writing runtime artifacts
- the same stream contract should remain usable later by Discord

## Live input expectations (Phase 4.10)

Codex is also a first-wave candidate for live session input and interactive turns.

For the first pass:
- AUDiaGentic should own stdin/input capture and normalized session-input persistence
- the Codex wrapper should tee live input or control turns to the console when interactive mode is enabled
- the provider should not be responsible for writing runtime input artifacts
- the same input contract should remain usable later by Discord

## Related docs

- `docs/specifications/architecture/providers/03_Codex.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-032.md`
- `docs/implementation/providers/12_Codex_Tag_Execution_Implementation.md`
- `docs/specifications/architecture/35_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/packets/phase-4/PKT-PRV-051.md`
