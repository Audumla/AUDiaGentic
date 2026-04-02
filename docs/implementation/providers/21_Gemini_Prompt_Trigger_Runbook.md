# Gemini prompt-trigger implementation runbook

## Purpose

This runbook turns the shared Phase 4.6 prompt-trigger contract into a Gemini-specific
implementation plan. It is intentionally narrow: it only covers Gemini chat exposure, the
required local assets, the hook-or-bridge decision, and the smoke tests that prove a tagged
prompt can launch the shared workflow runner.

## Scope

This runbook applies to:
- Gemini CLI
- Gemini Code Assist / editor companion surfaces
- the repository-owned Gemini bridge or hook normalization path

It does not redefine the canonical grammar. The grammar stays shared in the Phase 3.2 and
Phase 4.3 docs.

## Required outcomes

Gemini must expose the canonical prompt tags through a deterministic in-chat path:
- `@plan`
- `@implement`
- `@review`
- `@audit`
- `@check-in-prep`
- optional `@adhoc` only when the feature gate is enabled

The first non-empty line must be recognized before the chat loop continues. The normalized
request must enter the shared launch path without changing the canonical grammar.

## Current repo state

The repo now contains the Gemini bridge surface required by this runbook:

- `GEMINI.md`
- `tools/gemini_prompt_trigger_bridge.py`
- shared bridge harness in `src/audiagentic/execution/jobs/prompt_trigger_bridge.py`

## Gemini-specific exposure model

Gemini is a hybrid case. In the current design:
- `GEMINI.md` provides the project doctrine
- command templates define the canonical actions in a stable, user-visible way
- `BeforeAgent` or equivalent hooks can normalize the raw prompt when the active build
  supports them
- if hooks are not reliable, the repository bridge remains the source of truth

### Chat exposure flow

1. the user types a tagged prompt in Gemini CLI or the Gemini Code Assist surface
2. the active hook or repo bridge reads the first non-empty line
3. the canonical tag is resolved to the normalized launch action
4. `GEMINI.md` and the prompt-tag settings profile keep the mapping stable
5. the normalized request is sent to Gemini through the selected surface

### Canonical tag handling

The Gemini path must:
- inspect only the first non-empty line for the canonical tag
- map the tag to the same normalized action as the shared launcher
- preserve provider, surface, and session provenance
- preserve the raw prompt text in metadata
- never redefine the tag semantics in `GEMINI.md`

## Required local assets

Create or update:
- `GEMINI.md`
- command templates for `plan`, `implement`, `review`, `audit`, and `check-in-prep`
- optional hook scripts if the active build supports submit-time interception
- the Gemini prompt-tag settings profile

## Hook-or-bridge responsibilities

### BeforeAgent or equivalent hook

Responsibilities:
- inspect the raw user prompt
- detect the first-line canonical tag
- normalize the launch action
- preserve the original prompt in metadata
- inject launch context so Gemini enters the correct mode or command template

### Repository bridge

Responsibilities:
- perform the same normalization when the native hook surface is partial
- keep the canonical grammar outside the Gemini workspace config
- hand the normalized request to the shared launch contract

## Implementation sequence

1. add or update `GEMINI.md`
2. add the canonical command templates
3. wire the hook if the active Gemini build supports reliable pre-agent interception
4. keep the repo bridge as the fallback path
5. verify CLI and editor surfaces use the same normalized request shape
6. add smoke tests for `@plan`, `@implement`, and `@review`

## Smoke test matrix

### CLI smoke tests

- `@plan` should normalize into a plan request and reach the shared launcher
- `@implement` should normalize into an implementation request and reach the shared launcher
- `@review` should normalize into a review request and reach the shared launcher

### Editor smoke tests

- the same three tags must produce the same normalized launch envelope
- the same repo doctrine must apply
- the same fallback bridge must work if native hooks are disabled

## Acceptance criteria

- tagged Gemini prompts invoke the shared launcher path
- Gemini-specific instructions remain isolated from shared grammar docs
- the hook or bridge chain preserves provenance and raw prompt metadata
- the fallback bridge works if native hook interception is partial
- CLI and editor behavior remain aligned

## Rollback guidance

- remove the Gemini-specific hook and command templates first
- leave the shared prompt grammar untouched
- keep the shared bridge contract intact so other providers remain unaffected

## Related docs

- `docs/specifications/architecture/providers/04_Gemini.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-034.md`
- `docs/implementation/providers/14_Gemini_Tag_Execution_Implementation.md`
