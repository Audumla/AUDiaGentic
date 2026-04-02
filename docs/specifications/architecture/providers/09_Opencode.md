# opencode

## Purpose

Wrapper-first CLI provider for canonical `ag-*` prompt launches and coding-heavy tasks where the repository-owned bridge normalizes the request before execution.

## Canonical id
- `opencode`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
opencode typically uses `access-mode: cli`, with catalog refresh sourced from CLI or provider configuration.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: wrapper-normalize
- VS Code surface mode: unsupported
- settings profile: opencode-prompt-tags-v1
- alias and argument names resolve from `.audiagentic/prompt-syntax.yaml`

## Prompt-trigger exposure (Phase 4.6)

opencode exposes tags through repo guidance files plus a wrapper that normalizes the raw prompt before execution begins. Because opencode is wrapper-first, the repository bridge owns the canonical grammar and provenance fields.

### Chat exposure path
- user types the tagged prompt into opencode CLI or a wrapper surface
- the wrapper reads the first non-empty line and resolves the canonical action
- `AGENTS.md` instructs the repository contract for tagged prompts
- `.agents/skills/ag-*/SKILL.md` carries the action-specific prompt shape after normalization
- the wrapper injects the normalized envelope and launches opencode through the selected mode

### Required local assets
- `AGENTS.md`
- `.agents/skills/ag-plan/SKILL.md`
- `.agents/skills/ag-implement/SKILL.md`
- `.agents/skills/ag-review/SKILL.md`
- `.agents/skills/ag-audit/SKILL.md`
- `.agents/skills/ag-check-in-prep/SKILL.md`
- repo-owned wrapper or bridge command

### Fallback path
- if the wrapper cannot intercept the raw prompt, exact tag support must be treated as unavailable for that surface
- opencode-specific semantics stay isolated from the shared grammar docs

## Phase 4.6 implementation runbook

The implementation runbook for opencode prompt-trigger behavior lives at
`docs/implementation/providers/28_Opencode_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into opencode-specific
implementation steps, wrapper wiring, and smoke tests.

## Phase 4.9 live stream and progress capture

opencode is a wrapper-milestone provider in the first pass.

Recommended method:
- capture raw provider output through the shared bridge
- emit AUDiaGentic-owned wrapper milestones until a stable stream path is proven
- keep durable stream persistence owned by AUDiaGentic

## Phase 4.10 live input and interactive session control

opencode is a record-first provider in the first pass.

Recommended method:
- capture and persist input intent through the shared harness
- keep live-session continuation as a later enhancement, not an MVP guarantee
- avoid claiming mid-run input attachment until the real session behavior is proven

## Phase 4.11 structured completion and result normalization

opencode should prefer wrapper-bounded final-result normalization with fallback.

Recommended method:
- request a deterministic final completion surface when the provider surface is stable enough
- fall back to wrapper-derived normalization when direct result shaping is partial
- keep the direct-versus-fallback distinction visible in persisted artifacts

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
