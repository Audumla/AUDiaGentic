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

## Related docs

- `docs/specifications/architecture/providers/07_Cline.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-037.md`
- `docs/implementation/providers/17_Cline_Tag_Execution_Implementation.md`
