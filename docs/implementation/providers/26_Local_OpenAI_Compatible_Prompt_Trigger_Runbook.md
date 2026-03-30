# local-openai prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 bridge-only prompt-trigger path for local OpenAI-compatible backends.

## Scope

- local OpenAI-compatible backends
- repo-owned bridge / wrapper
- optional editor command pointing at the same bridge

## Current repo state

The local-openai bridge surface is already implemented in the repository through:

- `tools/local_openai_prompt_trigger_bridge.py`
- the shared `prompt-trigger-bridge` harness

Use this runbook as the implementation reference and smoke-test guide for that existing
bridge-only surface.

## Exposure model

local-openai is bridge-only. The repository bridge reads the first non-empty line, resolves the
canonical tag, and sends a normalized request to the backend without exposing tag parsing to the
backend itself.

## Required assets

- repo-owned bridge or wrapper script
- provider config and model catalog entries
- optional editor command that points at the same bridge

## Smoke tests

- `@plan` reaches the shared launcher
- `@implement` reaches the shared launcher
- `@review` reaches the shared launcher

## Acceptance

- canonical tags are exposed only through the bridge
- backend remains tag-opaque
- fallback bridge remains authoritative

## Related docs

- `docs/specifications/architecture/providers/01_Local_OpenAI_Compatible.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-038.md`
- `docs/implementation/providers/18_Local_OpenAI_Compatible_Tag_Execution_Implementation.md`
