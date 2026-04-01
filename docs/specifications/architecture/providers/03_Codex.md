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
- alias and argument names resolve from `.audiagentic/prompt-syntax.yaml`


## Prompt-trigger exposure (Phase 4.6)

Codex exposes tags through repo guidance files plus a wrapper that normalizes the raw prompt
before Codex begins its own execution flow. Because a documented arbitrary pre-submit hook is
not confirmed here, exact tag handling belongs in the repository bridge rather than in Codex
itself.

### Exact mechanics

1. the user types a canonical tag on the first non-empty line
2. the repo-owned wrapper reads the raw prompt and preserves provenance
3. `AGENTS.md` instructs Codex to treat the tag as a launch request
4. `.agents/skills/*/SKILL.md` maps the canonical action to a narrow action shape
5. the bridge preflights `AGENTS.md` and the five canonical skill files
6. the bridge hands the normalized envelope to `prompt-launch`
7. the jobs layer persists the job record and review/release artifacts

### Chat exposure path
- user types a tagged prompt in Codex CLI or the Codex VS Code surface
- the wrapper reads the first non-empty line and resolves the canonical action
- the wrapper validates the required prompt-calling assets before launch
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

## Phase 4.9 live stream and progress capture

Codex is a first-wave validation provider for the shared live-stream contract because the repo
already uses a stable wrapper path for prompt-trigger launches.

For the first pass:
- AUDiaGentic should tee live console progress while owning persistence
- Codex should not be responsible for writing runtime stream artifacts
- normalized progress records should be written under the job runtime folder
- final structured artifacts should still be written after the stream completes
- Codex should use wrapper milestone events plus raw log retention unless and until a richer native event surface proves more stable

## Phase 4.10 live input and interactive session control

Codex is also a first-wave validation provider for the shared live-input contract because the
repo already uses a stable wrapper path for prompt-trigger launches and can reopen the same
provider session for controlled follow-up input.

For the first pass:
- AUDiaGentic should own stdin/input capture and normalized session-input persistence
- the Codex wrapper should tee live input or control turns to the console when interactive mode is enabled
- the provider should not be responsible for writing runtime input artifacts
- the same input contract should remain usable later by Discord or another overlay
- recorded/queued input is the current guaranteed level; true mid-run live-session attachment remains a later session-manager seam

## Phase 4.11 structured completion and result normalization

Codex is a first-wave validation provider for shared structured completion.

For the first pass:
- prefer the final-message/result-file path as the canonical completion surface
- request deterministic JSON in the final Codex result
- persist direct provider results when parsing succeeds
- mark wrapper-derived fallback results explicitly when direct JSON is unavailable

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope

## Implementation note

The local adapter now exists and calls `codex exec` through a thin wrapper, but
provider-specific task payload enrichment still needs to be threaded through the
job/provider boundary if Codex should receive more than structural packet context.
