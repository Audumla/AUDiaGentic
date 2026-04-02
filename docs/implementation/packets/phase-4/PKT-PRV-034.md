# PKT-PRV-034 — Gemini prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** IN_PROGRESS
**Owner:** Gemini

## Objective

Wire Gemini instruction surfaces and command templates to the shared trigger bridge so tagged
prompts can launch jobs.  Every canonical tag must be reachable through a stable, repo-owned
file surface before this packet is READY_FOR_REVIEW.

## What is implemented

- `GEMINI.md` records the canonical tag doctrine and bridge usage
- `tools/gemini_prompt_trigger_bridge.py` provides the Gemini-specific wrapper path to the
  shared bridge
- the shared bridge harness is implemented and test-covered

## What is NOT yet implemented (blockers for READY_FOR_REVIEW)

- **No command templates** — `.gemini/commands/` directory does not exist; no per-tag
  instruction files for plan / implement / review / audit / check-in-prep
- **No `BeforeAgent` hook configuration** — `.gemini/settings.json` or equivalent hook wiring
  is absent
- **No Gemini prompt-tag settings profile** — tag mapping is undocumented in any
  Gemini-native config file
- **No smoke tests** — no integration tests for the Gemini prompt-trigger path

## Required instruction surface

Gemini exposes tags through workspace instructions and command templates.  The required
file layout is:

```text
.gemini/
  commands/
    plan.md          # @plan command template
    implement.md     # @implement command template
    review.md        # @review command template
    audit.md         # @audit command template
    check-in-prep.md # @check-in-prep command template
  settings.json      # BeforeAgent hook config (optional, use bridge as fallback)
```

Each command template must follow the same structure as `.agents/skills/*/SKILL.md`:

```yaml
---
name: <action>
description: <one-line description>
---

# <action> skill

Trigger / Do / Do not rules matching the shared canonical contract.
```

If Gemini does not support YAML frontmatter in command templates, use plain markdown
with the same Trigger / Do / Do not structure — do not invent alternate semantics.

## Prompt-trigger exposure details

### User-facing flow

1. user types the tagged prompt into Gemini CLI or the Gemini Code Assist surface
2. the `BeforeAgent` hook (or the bridge if the hook is unavailable) reads the first
   non-empty line and resolves the canonical action
3. `GEMINI.md` and the command templates keep the tag mapping stable
4. the normalized envelope is submitted to the shared bridge

### Failure mode

If the active Gemini build does not expose a stable `BeforeAgent` hook, the repository
bridge remains authoritative and the native hook path is treated as partial.

## Prerequisites

- PKT-PRV-031 verified
- PKT-PRV-006 verified

## Implementation steps

1. Create `.gemini/commands/` with one file per canonical tag (plan, implement, review,
   audit, check-in-prep) using the shared Trigger / Do / Do not structure
2. Add YAML frontmatter to each command template if supported by the Gemini CLI version
3. Create `.gemini/settings.json` with `BeforeAgent` hook wiring to the bridge (or document
   why the bridge-only path is the stable fallback for this provider)
4. Add smoke tests for `@plan` and `@review` via the Gemini bridge
5. Verify CLI and editor surfaces produce the same normalized launch envelope

## Acceptance criteria

- `.gemini/commands/` exists with all 5 canonical tag files
- each command file uses the shared Trigger / Do / Do not structure
- tagged Gemini prompts reach the shared launcher path via bridge or hook
- Gemini-specific instruction files do not redefine the canonical grammar
- smoke tests pass for at least `@plan` and `@review`

## Files to create or update

- `.gemini/commands/plan.md`
- `.gemini/commands/implement.md`
- `.gemini/commands/review.md`
- `.gemini/commands/audit.md`
- `.gemini/commands/check-in-prep.md`
- `.gemini/settings.json` (hook config or documented fallback note)
- `docs/implementation/providers/21_Gemini_Prompt_Trigger_Runbook.md`
- Gemini prompt-trigger smoke tests

## Rollback guidance

- revert `.gemini/` directory changes only
- leave the shared launch grammar untouched
- `GEMINI.md` and the bridge tool remain in place
