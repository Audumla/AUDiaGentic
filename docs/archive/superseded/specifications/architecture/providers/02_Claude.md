# claude

## Purpose

Optional premium provider for jobs and later higher-quality summaries.

## Canonical id
- `claude`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Claude typically uses `access-mode: cli` or `env`, with catalog refresh sourced from CLI or API.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: wrapper-normalize
- VS Code surface mode: extension-normalize
- settings profile: claude-prompt-tags-v1


## Prompt-trigger exposure (Phase 4.6)

Claude exposes tags through native project instruction files and the prompt-submit hook. The
chat surface can therefore inspect the first-line tag before Claude begins planning, then
normalize the request into the shared launch envelope.

### Chat exposure path
- user types the tagged prompt into Claude Code CLI or the Claude VS Code surface
- `UserPromptSubmit` reads the raw text, resolves the canonical action, and injects the
  normalized launch metadata
- `CLAUDE.md` and `.claude/rules/*.md` hold the canonical tag doctrine and review policy
- `.claude/skills/**/SKILL.md` carries the action-specific prompt shape after normalization
- `PreToolUse` narrows tool access once the action is known

### Required local assets
- `CLAUDE.md`
- `.claude/rules/prompt-tags.md`
- `.claude/rules/review-policy.md`
- `.claude/skills/ag-plan/SKILL.md`
- `.claude/skills/ag-implement/SKILL.md`
- `.claude/skills/ag-review/SKILL.md`
- `.claude/skills/ag-audit/SKILL.md`
- `.claude/skills/ag-check-in-prep/SKILL.md`

### Fallback path
- if the hook chain is partial, the same normalized request must be emitted by the shared
  bridge wrapper
- Claude-specific semantics stay isolated from the shared grammar docs

## Phase 4.6 implementation runbook

The implementation runbook for Claude prompt-trigger behavior lives at
`docs/implementation/providers/20_Claude_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Claude-specific
implementation steps, hook wiring, and smoke tests.

## Phase 4.9 live stream and progress capture

Claude is a wrapper-milestone provider in the first pass.

Recommended method:
- capture raw provider output through the shared bridge
- emit AUDiaGentic-owned wrapper milestones until a stable hook-backed stream path is proven
- keep durable stream persistence owned by AUDiaGentic

## Phase 4.10 live input and interactive session control

Claude is a record-first provider in the first pass.

Recommended method:
- capture and persist input intent through the shared harness
- keep hook-assisted live-session continuation as a later enhancement, not an MVP guarantee
- avoid claiming mid-run live input attachment until the real session behavior is proven

## Phase 4.11 structured completion and result normalization

Claude should prefer hook-backed or wrapper-bounded JSON completion with wrapper fallback.

Recommended method:
- request JSON-only final completion when the surface is stable enough
- fall back to wrapper-derived normalization when the hook path is partial
- keep the direct-versus-fallback distinction visible in persisted artifacts

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
