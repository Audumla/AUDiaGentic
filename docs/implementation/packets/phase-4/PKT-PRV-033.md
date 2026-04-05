# PKT-PRV-033 — Claude prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** VERIFIED
**Owner:** Claude

## Objective
Wire Claude Code or its repo-local instruction files to the shared trigger bridge so tagged prompts launch the shared workflow runner.

## Current implementation state

### ✅ Already in place

- `CLAUDE.md` records the canonical tag doctrine and bridge usage
- `.claude/rules/prompt-tags.md` and `.claude/rules/review-policy.md` exist and define tag/review doctrine
- `tools/claude_prompt_trigger_bridge.py` provides the Claude-specific wrapper path to shared bridge
- the shared bridge harness is already implemented and test-covered
- `tests/integration/providers/test_claude_prompt_trigger_bridge.py` proves the wrapper works

### ✅ Option A completion state

- `.claude/skills/ag-{plan,implement,review,audit,check-in-prep}/SKILL.md` — canonical
  managed skill definitions
- preflight validation in `tools/claude_prompt_trigger_bridge.py` — required assets checked
  before launch
- tests verify missing assets return validation error before launch
- Option A is the baseline and Option B remains the native-hook follow-on

## Future: Option B native hook

After PKT-PRV-033 is VERIFIED, Option B (native UserPromptSubmit + PreToolUse hooks) will be tracked as **PKT-PRV-055**.

## Prompt-trigger exposure details

Claude can expose tags natively through `UserPromptSubmit`, so the chat surface itself can
normalize the tag before planning starts.

### User-facing flow
1. user types the tagged prompt into Claude Code CLI or the Claude VS Code surface
2. `UserPromptSubmit` reads the prompt and resolves the canonical action
3. the hook injects the normalized launch metadata and chooses the right rule/skill path
4. `PreToolUse` tightens the tool policy for the selected stage

### Required files/settings
- `CLAUDE.md`
- `.claude/rules/prompt-tags.md`
- `.claude/rules/review-policy.md`
- `.claude/skills/ag-plan/SKILL.md`
- `.claude/skills/ag-implement/SKILL.md`
- `.claude/skills/ag-review/SKILL.md`
- `.claude/skills/ag-audit/SKILL.md`
- `.claude/skills/ag-check-in-prep/SKILL.md`
- hook configuration for `UserPromptSubmit` and `PreToolUse`

### Verification focus
- CLI smoke test for `@plan`
- CLI smoke test for `@review`
- VS Code surface smoke test using the same hook chain

### Failure mode
If the hook chain is partial, the provider must fall back to the shared bridge wrapper and
keep the canonical grammar unchanged.

## Prerequisites
- PKT-PRV-031 is verified
- PKT-PRV-004 is verified

## Implementation steps
1. define or update Claude instruction files and rule surfaces
2. bridge Claude prompt submission to the shared launch wrapper
3. keep hook / rule / skill details isolated to Claude
4. add Claude prompt-trigger smoke tests

## Acceptance criteria
- tagged Claude prompts invoke the shared launcher path
- the repo instruction surface remains the single source of truth
- the fallback bridge works if hook interception is partial

## Likely files or surfaces
- CLAUDE.md
- .claude/rules
- .claude/skills
- docs/implementation/providers/20_Claude_Prompt_Trigger_Runbook.md
- Claude prompt-trigger smoke tests

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
