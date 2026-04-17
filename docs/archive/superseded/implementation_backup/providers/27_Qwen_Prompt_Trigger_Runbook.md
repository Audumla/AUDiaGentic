# Qwen prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 Qwen prompt-trigger path using experimental hooks when enabled and the
repo bridge as fallback.

## Scope

- Qwen Code CLI
- companion VS Code surface where available
- repo-owned bridge / hook path

## Current repo state

The Qwen bridge surface is already implemented in the repository through:

- `tools/qwen_prompt_trigger_bridge.py`
- the shared `prompt-trigger-bridge` harness

Use this runbook as the implementation reference and smoke-test guide for that existing
bridge fallback surface.

## Exposure model

Qwen is a guarded native-intercept candidate. Experimental hooks can normalize the first-line
tag when enabled; otherwise the repository bridge remains authoritative.

## Required assets

- `.qwen/settings.json`
- experimental hook scripts
- optional repo guidance doc for canonical tag doctrine
- repo-owned bridge fallback

## Smoke tests

- `@plan` reaches the shared launcher
- `@implement` reaches the shared launcher
- `@review` reaches the shared launcher

## Acceptance

- canonical tags are exposed in chat through hooks or bridge
- Qwen-specific instructions stay isolated
- fallback bridge works if experimental hooks are unavailable

## Related docs

- `docs/specifications/architecture/providers/08_Qwen.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-038.md`
- `docs/implementation/providers/19_Qwen_Tag_Execution_Implementation.md`
