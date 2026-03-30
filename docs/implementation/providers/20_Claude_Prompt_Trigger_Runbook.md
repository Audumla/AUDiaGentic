# Claude prompt-trigger implementation runbook

## Purpose

This runbook turns the shared Phase 4.6 prompt-trigger contract into a Claude-specific
implementation plan. It is intentionally narrow: it only covers the Claude chat exposure path,
the required repo-local assets, and the smoke tests that prove a tagged prompt can launch the
shared workflow runner.

## Scope

This runbook applies to:
- Claude Code CLI
- Claude Code VS Code surface
- the repository-owned Claude hook / instruction surface

It does not define the canonical grammar. The grammar remains shared in the Phase 3.2 and
Phase 4.3 docs.

## Required outcomes

Claude must expose the canonical prompt tags through a deterministic in-chat path:
- `@plan`
- `@implement`
- `@review`
- `@audit`
- `@check-in-prep`
- optional `@adhoc` only if the feature gate is enabled

The first non-empty line in the prompt must be recognized before Claude begins planning.
The normalized result must enter the shared launch path without changing the canonical grammar.

## Current repo state

The repo now contains the Claude bridge surface required by this runbook:

- `CLAUDE.md`
- `.claude/rules/prompt-tags.md`
- `.claude/rules/review-policy.md`
- `tools/claude_prompt_trigger_bridge.py`

## Claude-specific exposure model

Claude is the clearest native-hook candidate in the current matrix because it has:
- `CLAUDE.md`
- `.claude/rules/*.md`
- `.claude/skills/**/SKILL.md`
- `UserPromptSubmit`
- `PreToolUse`

### Chat exposure flow

1. the user types a tagged prompt in Claude Code CLI or the Claude VS Code surface
2. `UserPromptSubmit` reads the raw prompt before planning starts
3. the hook resolves the canonical tag and injects the normalized launch metadata
4. `CLAUDE.md` and `.claude/rules/*` define the repository doctrine
5. `.claude/skills/*` provide the action-specific behavior after normalization
6. `PreToolUse` narrows tools and stage behavior for the selected action

### Canonical tag handling

The hook must:
- inspect only the first non-empty line for the canonical tag
- map the tag to the same normalized action as the shared launcher
- preserve provider, surface, and session provenance
- preserve the raw prompt text in metadata
- refuse to invent alternate tag meanings

## Required repo-local assets

Create or update:
- `CLAUDE.md`
- `.claude/rules/prompt-tags.md`
- `.claude/rules/review-policy.md`
- `.claude/skills/plan/SKILL.md`
- `.claude/skills/implement/SKILL.md`
- `.claude/skills/review/SKILL.md`
- `.claude/skills/audit/SKILL.md`
- `.claude/skills/check-in-prep/SKILL.md`
- optional `.claude/skills/adhoc/SKILL.md`

## Hook responsibilities

### UserPromptSubmit

Responsibilities:
- inspect the raw user prompt
- detect the first-line canonical tag
- normalize the launch action
- preserve the original prompt in metadata
- inject launch context so Claude enters the correct skill/rules path

### PreToolUse

Responsibilities:
- enforce stage restrictions
- keep review mode read-focused unless explicitly elevated
- prevent tracked-doc mutations when the selected action does not permit them
- keep the tool policy aligned with the canonical stage

## Implementation sequence

1. add or update `CLAUDE.md`
2. add prompt-tag and review-policy rules under `.claude/rules/`
3. add or update the five canonical skills
4. wire `UserPromptSubmit` to the shared trigger bridge
5. wire `PreToolUse` to the stage restriction policy
6. verify CLI and VS Code surfaces use the same normalized request shape
7. add smoke tests for `@plan`, `@implement`, and `@review`

## Smoke test matrix

### CLI smoke tests

- `@plan` should normalize into a plan request and reach the shared launcher
- `@implement` should normalize into an implementation request and reach the shared launcher
- `@review` should normalize into a review request and reach the shared launcher

### VS Code smoke tests

- the same three tags must produce the same normalized launch envelope
- the same repo rules must apply
- the same tool restrictions must apply

## Acceptance criteria

- tagged Claude prompts invoke the shared launcher path
- Claude-specific instructions remain isolated from shared grammar docs
- the hook chain preserves provenance and raw prompt metadata
- the fallback bridge works if the hook chain is partial
- CLI and VS Code behavior remain aligned

## Rollback guidance

- remove the Claude-specific hook and rules first
- leave the shared prompt grammar untouched
- keep the shared bridge contract intact so other providers remain unaffected

## Related docs

- `docs/specifications/architecture/providers/02_Claude.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-033.md`
- `docs/implementation/providers/13_Claude_Code_Tag_Execution_Implementation.md`
