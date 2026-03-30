# gemini

## Purpose

Optional provider with structured output and job support through provider adapter.

## Canonical id
- `gemini`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Gemini typically uses `access-mode: cli` or `env`, with catalog refresh sourced from CLI or API.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: wrapper-normalize
- VS Code surface mode: extension-normalize
- settings profile: gemini-prompt-tags-v1


## Prompt-trigger exposure (Phase 4.6)

Gemini exposes tags through its workspace instruction file, command-template surface, and any
available prompt-submit or hook path in the active build. The provider should use the
first-line tag to select the canonical action before the chat proceeds.

### Chat exposure path
- user types the tagged prompt into Gemini CLI or the Gemini Code Assist surface
- the local normalizer reads the first non-empty line and maps it to the canonical action
- `GEMINI.md` and the prompt-tag settings profile keep the mapping consistent
- where a native prompt-submit hook exists, it handles the normalization directly
- where the native surface is instruction-only, the repo bridge injects the same normalized
  envelope before dispatch

### Required local assets
- `GEMINI.md`
- command templates for plan / implement / review / audit / check-in-prep
- optional hook or bridge script used by the active Gemini surface

### Fallback path
- if the active Gemini build does not expose a stable submit hook, the repo-owned bridge
  remains authoritative
- the canonical grammar stays in the repository contract, not in the Gemini workspace rules

Current repo state:
- `GEMINI.md`
- `tools/gemini_prompt_trigger_bridge.py`
- shared bridge harness in `src/audiagentic/jobs/prompt_trigger_bridge.py`

## Phase 4.6 implementation runbook

The implementation runbook for Gemini prompt-trigger behavior lives at
`docs/implementation/providers/21_Gemini_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Gemini-specific
implementation steps, hook-or-bridge wiring, and smoke tests.

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
