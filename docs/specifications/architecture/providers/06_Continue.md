# continue

## Purpose

Optional provider surface that may wrap external provider models.

## Canonical id
- `continue`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Continue typically uses `access-mode: cli`, with catalog refresh sourced from CLI or API.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: wrapper-normalize
- VS Code surface mode: extension-normalize
- settings profile: continue-prompt-tags-v1


## Prompt-trigger exposure (Phase 4.6)

Continue exposes tags through its config-driven prompt templates and rules. The wrapper maps
the first-line tag to a predeclared Continue invocation, then hands the normalized envelope
to the Continue surface that owns the current workspace.

### Chat exposure path
- user types the tagged prompt into Continue-backed chat or editor integration
- the wrapper reads the first non-empty line and resolves the canonical action
- `config.yaml` and rule files carry the Continue-specific prompt doctrine
- invokable prompts or templates provide the mapped destination after normalization
- the same wrapper behavior is used in CLI and VS Code surfaces

### Required local assets
- Continue `config.yaml`
- Continue rule files
- prompt templates or invokable prompts for each canonical action
- repo-owned wrapper or bridge command

### Fallback path
- if the Continue surface cannot consume the normalized request directly, the bridge wrapper
  remains the source of truth
- Continue must not redefine the canonical tag semantics on its own

## Phase 4.6 implementation runbook

The implementation runbook for Continue prompt-trigger behavior lives at
`docs/implementation/providers/24_Continue_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Continue-specific
implementation steps, wrapper routing, and smoke tests.

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
