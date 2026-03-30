# PKT-PRV-037 — Cline prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** READY_FOR_REVIEW
**Owner:** Cline

## Objective
Wire Cline rules or hooks to the shared trigger bridge so tagged prompts launch the shared workflow runner.

## Current implementation

- `.clinerules/prompt-tags.md` now records the canonical tag doctrine
- `.clinerules/review-policy.md` now records the review policy
- `tools/cline_prompt_trigger_bridge.py` provides the Cline-specific wrapper path to the shared bridge
- the shared bridge harness is already implemented and test-covered


## Prompt-trigger exposure details

Cline can expose tags through `.clinerules`, hooks, and workflow configuration. The chat
surface should normalize the first-line tag before the workflow engine begins so the stage
selection remains deterministic.

### User-facing flow
1. user types the tagged prompt into Cline chat or the Cline VS Code surface
2. a prompt hook or equivalent entry point reads the first non-empty line and resolves the
   canonical action
3. `.clinerules` and workflow files apply the canonical review and tool policies
4. the normalized request is handed to the matching workflow or task mode

### Required files/settings
- `.clinerules/*.md`
- Cline hook configuration
- Cline workflow files or task definitions
- repo-owned fallback bridge for environments where hooks are feature-gated

### Verification focus
- CLI smoke test for `@plan`
- CLI smoke test for `@review`
- VS Code smoke test if the hook executes in the editor surface

### Failure mode
If hook execution is unavailable, the shared wrapper must perform the same normalization and
the provider-specific workflow details must stay isolated from the shared grammar docs.

## Prerequisites
- PKT-PRV-031 is drafted
- PKT-PRV-009 is verified

## Implementation steps
1. define or update `.clinerules` and hook guidance
2. bridge Cline prompt submission to the shared launch wrapper
3. keep Cline-specific workflow and hook details isolated
4. add Cline prompt-trigger smoke tests

## Acceptance criteria
- tagged Cline prompts reach the shared launcher path
- Cline rules do not redefine the canonical grammar
- the fallback bridge works when hook execution is feature-gated

## Likely files or surfaces
- .clinerules/*.md
- Cline hooks and workflows
- `docs/implementation/providers/25_Cline_Prompt_Trigger_Runbook.md`
- Cline prompt-trigger smoke tests

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
