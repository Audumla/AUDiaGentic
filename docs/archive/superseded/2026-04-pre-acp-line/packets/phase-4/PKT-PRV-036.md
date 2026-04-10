# PKT-PRV-036 — Continue prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** DEFERRED_DRAFT
**Owner:** Continue

## Objective
Wire Continue config and rules to the shared trigger bridge so tagged prompts launch the shared workflow runner.


## Prompt-trigger exposure details

Continue exposes tags through config-driven prompts and rule files. The wrapper maps the
first-line tag to a predeclared Continue invocation, then hands the normalized envelope to
the Continue surface that owns the workspace.

### User-facing flow
1. user types the tagged prompt into Continue-backed chat or editor integration
2. the wrapper reads the first non-empty line and resolves the canonical action
3. `config.yaml` and rule files carry the Continue-specific tag doctrine
4. the wrapper selects the matching prompt template or invokable prompt and forwards the
   normalized request

### Required files/settings
- Continue `config.yaml`
- Continue rule files
- prompt templates or invokable prompts for each canonical action
- repo-owned wrapper or bridge command

### Verification focus
- CLI or editor smoke test for `@plan`
- CLI or editor smoke test for `@review`
- prompt template verification for the selected action path

### Failure mode
If Continue cannot consume the normalized request directly, the bridge wrapper remains the
source of truth and the provider must not redefine the canonical grammar.

## Prerequisites
- PKT-PRV-031 is drafted
- PKT-PRV-008 is verified

## Implementation steps
1. define or update Continue config and rule surfaces
2. bridge Continue prompt submission to the shared launch wrapper
3. keep Continue-specific invocation details isolated
4. add Continue prompt-trigger smoke tests

## Acceptance criteria
- tagged Continue prompts reach the shared launcher path
- Continue config remains the provider-specific source of truth
- the fallback bridge remains stable for local validation

## Likely files or surfaces
- Continue config.yaml
- Continue rule files
- `docs/implementation/providers/24_Continue_Prompt_Trigger_Runbook.md`
- Continue prompt-trigger smoke tests

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
