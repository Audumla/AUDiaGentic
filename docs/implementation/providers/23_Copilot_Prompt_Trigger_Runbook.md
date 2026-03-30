# Copilot prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 Copilot prompt-trigger path using repository instructions, prompt
files, agents, and a wrapper that normalizes tagged prompts first.

## Scope

- Copilot Chat
- Copilot CLI where available
- VS Code agent mode
- repo-owned wrapper / bridge

## Current repo state

The Copilot bridge surface is already implemented in the repository through:

- `.github/copilot-instructions.md`
- `.github/prompts/*.prompt.md`
- `.github/agents/*.agent.md`
- `tools/copilot_prompt_trigger_bridge.py`

Use this runbook as the implementation reference and smoke-test guide for that existing
surface.

## Exposure model

Copilot is adapter-driven. The wrapper reads the first non-empty line, resolves the canonical
tag, then selects the appropriate prompt file or agent after normalization.

## Required assets

- `.github/copilot-instructions.md`
- `.github/prompts/*.prompt.md`
- `.github/agents/*.agent.md`
- optional repo `AGENTS.md`
- repo-owned wrapper or bridge command

## Smoke tests

- `@plan` reaches the shared launcher
- `@implement` reaches the shared launcher
- `@review` reaches the shared launcher

## Acceptance

- canonical tags are exposed in chat through the wrapper
- Copilot-specific instructions stay isolated
- fallback bridge works if routing is partial

## Related docs

- `docs/specifications/architecture/providers/05_Copilot.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-035.md`
- `docs/implementation/providers/15_GitHub_Copilot_Tag_Execution_Implementation.md`
