# Continue prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 Continue prompt-trigger path using config-driven prompts, rules, and
a wrapper that normalizes tagged prompts first.

## Scope

- Continue-backed chat/editor surfaces
- Continue config and rules
- repo-owned wrapper / bridge

## Exposure model

Continue is adapter-driven. The wrapper reads the first non-empty line, resolves the canonical
tag, then selects a prompt template or invokable prompt after normalization.

## Required assets

- Continue `config.yaml`
- Continue rule files
- prompt templates or invokable prompts for each canonical action
- repo-owned wrapper or bridge command

## Smoke tests

- `@plan` reaches the shared launcher
- `@implement` reaches the shared launcher
- `@review` reaches the shared launcher

## Acceptance

- canonical tags are exposed in chat through the wrapper
- Continue-specific instructions stay isolated
- fallback bridge works if routing is partial

## Related docs

- `docs/specifications/architecture/providers/06_Continue.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-036.md`
- `docs/implementation/providers/16_Continue_Tag_Execution_Implementation.md`
