# Cline prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 Cline prompt-trigger path using `.clinerules`, hooks, workflows, and a
fallback bridge when hook interception is not available.

## Scope

- Cline chat surfaces
- Cline VS Code surfaces
- repo-local hooks/rules/workflows

## Exposure model

Cline is a native-intercept candidate. A prompt hook or equivalent entry point reads the first
non-empty line, resolves the canonical tag, and hands the normalized request to the matching
workflow or task mode.

## Current repo state

The repo now contains the Cline bridge surface required by this runbook:

- `.clinerules/prompt-tags.md`
- `.clinerules/review-policy.md`
- `tools/cline_prompt_trigger_bridge.py`

## Required assets

- `.clinerules/*.md`
- Cline hook configuration
- Cline workflow files or task definitions
- repo-owned fallback bridge

## Smoke tests

- `@plan` reaches the shared launcher
- `@implement` reaches the shared launcher
- `@review` reaches the shared launcher

## Acceptance

- canonical tags are exposed in chat through hooks or fallback bridge
- Cline-specific instructions stay isolated
- fallback bridge works if hook interception is partial

## Live stream expectations (Phase 4.9)

Cline is a first-wave candidate for live console and runtime progress capture.

For the first pass:
- AUDiaGentic should tee live Cline progress to the console when streaming is enabled
- AUDiaGentic should persist normalized progress records in the job runtime folder
- Cline should continue to emit progress normally and should not own persistence
- the same stream contract should remain usable later by Discord

## Live input expectations (Phase 4.10)

Cline is also a first-wave candidate for live session input and interactive turns.

For the first pass:
- AUDiaGentic should own stdin/input capture and normalized session-input persistence
- AUDiaGentic should tee control/input turns to the console when interactive mode is enabled
- Cline should continue to emit responses normally and should not own file persistence
- the same input contract should remain usable later by Discord

## Related docs

- `docs/specifications/architecture/providers/07_Cline.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-037.md`
- `docs/implementation/providers/17_Cline_Tag_Execution_Implementation.md`
- `docs/specifications/architecture/35_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/packets/phase-4/PKT-PRV-051.md`
