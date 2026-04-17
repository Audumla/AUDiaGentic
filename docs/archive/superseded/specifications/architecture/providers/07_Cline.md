# cline

## Purpose

Compatibility provider; not primary for MVP due to token cost concerns.

## Canonical id
- `cline`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Cline typically uses `access-mode: cli`, with catalog refresh sourced from CLI or API.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: wrapper-normalize
- VS Code surface mode: extension-normalize
- settings profile: cline-prompt-tags-v1
- alias and argument names resolve from `.audiagentic/prompt-syntax.yaml`


## Prompt-trigger exposure (Phase 4.6)

Cline exposes tags through `.clinerules`, hooks, and workflow configuration. The chat surface
can normalize the first-line tag before the workflow engine begins, which makes Cline a
native-intercept candidate for canonical tags when the hook ordering is stable.

Current repo state:
- `.clinerules/prompt-tags.md`
- `.clinerules/review-policy.md`
- `.clinerules/skills/ag-*.md`
- `tools/cline_prompt_trigger_bridge.py`

### Chat exposure path
- user types the tagged prompt into Cline chat or the Cline VS Code surface
- a prompt hook or equivalent entry point reads the first non-empty line and resolves the
  canonical action
- `.clinerules` and workflow files define the tag doctrine and tool restrictions
- the normalized request is handed to the matching workflow or task mode

### Required local assets
- `.clinerules/prompt-tags.md`
- `.clinerules/review-policy.md`
- `.clinerules/skills/ag-plan.md`
- `.clinerules/skills/ag-implement.md`
- `.clinerules/skills/ag-review.md`
- `.clinerules/skills/ag-audit.md`
- `.clinerules/skills/ag-check-in-prep.md`
- Cline hook configuration
- Cline workflow files or task definitions
- repo-owned fallback bridge for environments where hooks are feature-gated

### Fallback path
- if hook execution is unavailable, the shared wrapper must perform the same normalization
- Cline-specific workflow details remain isolated from the shared grammar docs

## Phase 4.6 implementation runbook

The implementation runbook for Cline prompt-trigger behavior lives at
`docs/implementation/providers/25_Cline_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Cline-specific
implementation steps, hook wiring, and smoke tests.

## Phase 4.9 live stream and progress capture

Cline is a first-wave validation provider for the shared live-stream contract because it already
emits progress events that are useful for console mirroring.

For the first pass:
- AUDiaGentic should tee live Cline progress to the console if streaming is enabled
- AUDiaGentic should persist normalized progress records in the job runtime folder
- Cline should continue to emit progress normally and should not own file persistence
- final structured artifacts should still be written after the stream completes
- Cline should be the reference provider for native event extraction from `cline --json`

## Phase 4.10 live input and interactive session control

Cline is also a first-wave validation provider for the shared live-input contract because its
CLI behavior already exposes useful interactive turns during a session.

For the first pass:
- AUDiaGentic should own stdin/input capture and normalized session-input persistence
- AUDiaGentic should tee control/input turns to the console when interactive mode is enabled
- Cline should continue to emit responses normally and should not own file persistence
- the same input contract should remain usable later by Discord or another overlay
- recorded input is guaranteed now; true mid-run interactive attachment still depends on a later session/process manager

## Phase 4.11 structured completion and result normalization

Cline is a first-wave validation provider for shared structured completion.

For the first pass:
- prefer JSON completion returned through the `cline --json` path
- preserve the full NDJSON stream in raw logs
- persist direct provider findings when parsing succeeds
- mark synthetic/fallback review results explicitly when parsing fails

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
