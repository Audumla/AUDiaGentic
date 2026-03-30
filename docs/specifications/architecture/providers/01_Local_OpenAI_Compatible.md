# local-openai

## Purpose

HTTP OpenAI-compatible endpoint used heavily in MVP for deterministic and low-cost stages.

## Canonical id
- `local-openai`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Local OpenAI-compatible endpoints typically use `access-mode: none` and a `static` or `api` catalog source.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: bridge-wrapper
- VS Code surface mode: bridge-wrapper
- settings profile: openai-bridge-prompt-tags-v1


## Prompt-trigger exposure (Phase 4.6)

Local OpenAI-compatible backends do not own the user-facing prompt surface, so tags are
exposed only through the repo-owned bridge or wrapper that fronts the backend. When a user
types a tagged prompt in CLI or VS Code, the wrapper reads the first non-empty line,
resolves the canonical action, and hands a normalized `PromptLaunchRequest` to the shared
launcher before the backend sees any text.

### Chat exposure path
- user-facing tags are entered in the project launcher, not in the backend API itself
- the bridge reads `@plan`, `@implement`, `@review`, `@audit`, `@check-in-prep`, or
  shorthand provider aliases from the first non-empty line
- the bridge converts the request into the `openai-bridge-prompt-tags-v1` profile before
  dispatch
- the backend receives only the normalized task payload and never needs to parse the tag
  syntax itself

### Required local assets
- repo-owned bridge or wrapper script
- provider config and model catalog entries
- optional editor command that points at the same bridge

### Fallback path
- if a given surface cannot call the bridge directly, that surface must not claim exact tag
  support
- the canonical grammar stays repository-owned and is never moved into the backend layer

## Phase 4.6 implementation runbook

The implementation runbook for local-openai prompt-trigger behavior lives at
`docs/implementation/providers/26_Local_OpenAI_Compatible_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into bridge-only
implementation steps and smoke tests.

## Current repo state

The repository already contains the local-openai bridge wrapper:

- `tools/local_openai_prompt_trigger_bridge.py`
- shared `prompt-trigger-bridge` harness

The remaining work for local-openai is any future hookless UI integration beyond the existing
bridge path.

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
