# PKT-PRV-032 — Codex prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** READY_FOR_REVIEW
**Owner:** Codex

## Objective
Wire the Codex instruction surface to the shared trigger bridge so tagged prompts actually launch jobs.

## Current implementation

- `AGENTS.md` now records the canonical tag doctrine and bridge usage
- `.agents/skills/*/SKILL.md` exists for the canonical action set
- `tools/codex_prompt_trigger_bridge.py` provides the Codex-specific wrapper path to the shared bridge
- the shared bridge harness is already implemented and test-covered


## Prompt-trigger exposure details

Codex is wrapper-driven rather than raw-hook driven, so the chat surface becomes tag-aware
only when the repo-owned wrapper intercepts the first line and rewrites it into a Codex skill
request.

### User-facing flow
1. user types `@plan`, `@implement`, `@review`, `@audit`, or `@check-in-prep`
2. the wrapper reads the first non-empty line and resolves the canonical action
3. the wrapper injects the normalized envelope into Codex as an explicit skill-directed
   request
4. Codex loads `AGENTS.md` and the selected skill file before it starts work

### Required files/settings
- `AGENTS.md`
- `.agents/skills/ag-plan/SKILL.md`
- `.agents/skills/ag-implement/SKILL.md`
- `.agents/skills/ag-review/SKILL.md`
- `.agents/skills/ag-audit/SKILL.md`
- `.agents/skills/ag-check-in-prep/SKILL.md`
- repo-owned CLI or VS Code wrapper

### Verification focus
- CLI smoke test for `@plan`
- CLI smoke test for `@review`
- editor-surface smoke test if a Codex bridge is available there

### Failure mode
If the wrapper cannot intercept the prompt, the surface must be treated as plain chat and
must not be documented as exact canonical tag support.

## Prerequisites
- PKT-PRV-031 is drafted
- PKT-PRV-005 is verified

## Implementation steps
1. define or update `AGENTS.md` guidance for Codex
2. wire the Codex instruction surface or wrapper to the shared trigger bridge
3. document the Codex fallback path when native interception is unavailable
4. add Codex prompt-trigger smoke tests

## Acceptance criteria
- a tagged Codex prompt reaches the shared launcher path
- Codex-specific instructions remain isolated from shared grammar docs
- the implementation works whether Codex is launched from terminal or editor surface

## Likely files or surfaces
- AGENTS.md
- docs/specifications/architecture/providers/03_Codex.md
- `docs/implementation/providers/22_Codex_Prompt_Trigger_Runbook.md`
- Codex prompt-trigger smoke tests

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
