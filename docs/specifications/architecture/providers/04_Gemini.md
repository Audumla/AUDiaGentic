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
- `.gemini/commands/ag-plan.md`
- `.gemini/commands/ag-implement.md`
- `.gemini/commands/ag-review.md`
- `.gemini/commands/ag-audit.md`
- `.gemini/commands/ag-check-in-prep.md`
- optional hook or bridge script used by the active Gemini surface

### Fallback path
- if the active Gemini build does not expose a stable submit hook, the repo-owned bridge
  remains authoritative
- the canonical grammar stays in the repository contract, not in the Gemini workspace rules

Current repo state:
- `GEMINI.md`
- `tools/gemini_prompt_trigger_bridge.py`
- shared bridge harness in `src/audiagentic/execution/jobs/prompt_trigger_bridge.py`

## Phase 4.6 implementation runbook

The implementation runbook for Gemini prompt-trigger behavior lives at
`docs/implementation/providers/21_Gemini_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Gemini-specific
implementation steps, hook-or-bridge wiring, and smoke tests.

## Phase 4.9 live stream and progress capture

Gemini is a stdout-extract provider in the first pass.

Recommended method:
- preserve raw stdout/stderr in runtime logs
- extract only stable stream milestones from bounded wrapper output
- keep richer event normalization guarded until the runtime shape is proven

## Phase 4.10 live input and interactive session control

Gemini is a record-first provider in the first pass.

Recommended method:
- persist controlled input records and correlation metadata
- do not claim true live-session continuation until the wrapper/runtime path proves it

## Phase 4.11 structured completion and result normalization

Gemini should remain wrapper-first for structured completion.

Recommended method:
- use bounded prompts that request JSON-only final completion
- normalize wrapper output into the shared result envelope
- keep the provider in guarded status until deterministic completion parsing is proven

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
