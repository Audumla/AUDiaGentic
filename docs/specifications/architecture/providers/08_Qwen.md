# qwen

## Purpose

Qwen is treated as a local OpenAI-compatible provider in MVP, typically served through a local gateway.

## Canonical id
- `qwen`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Qwen typically uses `access-mode: none` with a `static` or `api` catalog source.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: bridge-wrapper
- VS Code surface mode: bridge-wrapper
- settings profile: openai-bridge-prompt-tags-v1


## Prompt-trigger exposure (Phase 4.6)

Qwen exposes tags through `.qwen/settings.json` and the experimental hook surface. When hooks
are enabled, the prompt-submit handler can normalize the first-line tag directly in the chat
surface; otherwise the repo bridge remains authoritative.

### Chat exposure path
- user types the tagged prompt into Qwen Code or the companion VS Code surface
- `UserPromptSubmit` or the equivalent experimental hook reads the first non-empty line
- the handler resolves the canonical action and injects the normalized launch metadata
- `settings.json` keeps the action mapping and feature flags aligned with the repository
  contract

### Required local assets
- `.qwen/settings.json`
- experimental hook scripts
- optional repo guidance doc for canonical tag doctrine
- repo-owned bridge fallback

### Fallback path
- if experimental hooks are disabled or unavailable, the repo bridge must handle exact tag
  support instead
- Qwen-specific behavior stays feature-gated until the same smoke tests pass across the
  supported surface

## Phase 4.6 implementation runbook

The implementation runbook for Qwen prompt-trigger behavior lives at
`docs/implementation/providers/27_Qwen_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Qwen-specific
implementation steps, hook-or-bridge wiring, and smoke tests.

## Current repo state

The repository already contains the Qwen bridge wrapper:

- `tools/qwen_prompt_trigger_bridge.py`
- shared `prompt-trigger-bridge` harness

The experimental hook path remains guarded, but the bridge fallback is now implemented.

## Phase 4.9 live stream and progress capture

Qwen is a bridge-first provider in the first pass.

Recommended method:
- preserve raw stdout/stderr or endpoint response logs
- normalize stream milestones only when the concrete runtime surface proves stable
- keep native hooks guarded until they earn a stronger role

## Phase 4.10 live input and interactive session control

Qwen is a record-first provider in the first pass.

Recommended method:
- persist input intent and correlation metadata through the shared harness
- do not claim true live-session continuation until the real provider surface proves it

## Phase 4.11 structured completion and result normalization

Qwen should stay bridge-first for completion normalization.

Recommended method:
- normalize CLI or endpoint completion into the shared result envelope
- keep the exact completion surface explicit when implementation begins
- maintain guarded status for native hook/session claims until proven

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
