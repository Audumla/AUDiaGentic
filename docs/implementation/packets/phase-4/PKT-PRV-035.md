# PKT-PRV-035 — GitHub Copilot prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** READY_FOR_REVIEW
**Owner:** GitHub Copilot

## Objective
Wire Copilot instruction files or custom agents to the shared trigger bridge so tagged prompts launch the shared workflow runner.

## Current implementation

- `.github/copilot-instructions.md` now records the canonical tag doctrine and bridge usage
- `.github/prompts/*.prompt.md` exists for the canonical action set
- `.github/agents/*.agent.md` exists for the canonical action set
- `tools/copilot_prompt_trigger_bridge.py` provides the Copilot-specific wrapper path to the shared bridge
- the shared bridge harness is already implemented and test-covered


## Prompt-trigger exposure details

Copilot exposes tags indirectly through repository instructions and custom prompt/agent
assets. The wrapper is what turns the raw tagged prompt into the Copilot surface that should
run.

### User-facing flow
1. user types the tagged prompt in Copilot Chat, Copilot CLI, or VS Code agent mode
2. the wrapper reads the first non-empty line and resolves the canonical action
3. the wrapper selects the correct prompt file or custom agent and forwards the normalized
   envelope
4. Copilot loads repository instructions and performs the requested stage

### Required files/settings
- `.github/copilot-instructions.md`
- `.github/prompts/*.prompt.md`
- `.github/agents/*.agent.md`
- optional repo `AGENTS.md`
- repo-owned wrapper or bridge command

### Verification focus
- CLI smoke test for `@plan`
- CLI smoke test for `@review`
- VS Code agent-mode smoke test with the same wrapper path

### Failure mode
If the wrapper is bypassed, exact canonical tag support is not guaranteed and must not be
claimed in the provider docs.

## Prerequisites
- PKT-PRV-031 is drafted
- PKT-PRV-007 is verified

## Implementation steps
1. define or update `.github/copilot-instructions.md` and any custom agent guidance
2. bridge Copilot prompt submission to the shared launch wrapper
3. keep the bridge narrow so Copilot semantics stay isolated
4. add Copilot prompt-trigger smoke tests

## Acceptance criteria
- tagged Copilot prompts reach the shared launcher path
- Copilot instructions remain repository-owned and isolated
- the fallback bridge works when Copilot needs interactive approval constraints

## Likely files or surfaces
- .github/copilot-instructions.md
- custom Copilot agent prompts
- `docs/implementation/providers/23_Copilot_Prompt_Trigger_Runbook.md`
- Copilot prompt-trigger smoke tests

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
