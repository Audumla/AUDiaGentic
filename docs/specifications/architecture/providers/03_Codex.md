# codex

## Purpose

Optional provider for coding-heavy stages after provider layer lands.

## Canonical id
- `codex`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Codex typically uses `access-mode: cli` or `env`, with catalog refresh sourced from CLI or API.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: wrapper-normalize
- VS Code surface mode: extension-normalize
- settings profile: codex-prompt-tags-v1


## Prompt-trigger exposure (Phase 4.6)

Codex exposes tags through repo guidance files plus a wrapper that normalizes the raw prompt
before Codex begins its own execution flow. Because a documented arbitrary pre-submit hook is
not confirmed here, exact tag handling belongs in the repository bridge rather than in Codex
itself.

### Chat exposure path
- user types a tagged prompt in Codex CLI or the Codex VS Code surface
- the wrapper reads the first non-empty line and resolves the canonical action
- `AGENTS.md` provides the project doctrine and the tag-to-skill guidance
- `.agents/skills/**/SKILL.md` provides the action-specific prompt shape after normalization
- the wrapper injects the normalized envelope and then launches Codex through the selected
  skill or execution mode

### Required local assets
- `AGENTS.md`
- `.agents/skills/plan/SKILL.md`
- `.agents/skills/implement/SKILL.md`
- `.agents/skills/review/SKILL.md`
- `.agents/skills/audit/SKILL.md`
- `.agents/skills/check-in-prep/SKILL.md`
- repo-owned wrapper or bridge command

### Fallback path
- if the wrapper cannot intercept the raw prompt, exact tag support must be treated as not
  available for that surface
- Codex must never be documented as parsing custom tags natively unless the wrapper is in
  place

## Phase 4.6 implementation runbook

The implementation runbook for Codex prompt-trigger behavior lives at
`docs/implementation/providers/22_Codex_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Codex-specific
implementation steps, wrapper wiring, and smoke tests.

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope

## Implementation note

The local adapter now exists and calls `codex exec` through a thin wrapper, but
provider-specific task payload enrichment still needs to be threaded through the
job/provider boundary if Codex should receive more than structural packet context.
