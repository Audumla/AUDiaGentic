# PKT-PRV-037 — Cline prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** IN_PROGRESS
**Owner:** Cline

## Objective

Wire Cline rules, hooks, and per-tag skill files to the shared trigger bridge so tagged
prompts launch the shared workflow runner.  Per-tag skill files and at least a documented
hook-or-fallback path must exist before this packet is READY_FOR_REVIEW.

## What is implemented

- `.clinerules/prompt-tags.md` records the canonical tag doctrine
- `.clinerules/review-policy.md` records the review policy
- `tools/cline_prompt_trigger_bridge.py` provides the Cline-specific wrapper path to the
  shared bridge
- the shared bridge harness is implemented and test-covered

## What is NOT yet implemented (blockers for READY_FOR_REVIEW)

- **No per-tag skill files** — `.clinerules/` contains only doctrine and policy docs; there
  are no per-action skill or instruction files equivalent to `.agents/skills/` or
  `.claude/skills/`
- **No hook configuration** — no Cline hook setup that normalizes the first-line tag before
  the workflow engine starts
- **No workflow definitions** — no Cline workflow or task-definition files for the canonical
  actions
- **No smoke tests** — no integration tests for the Cline prompt-trigger path

## Required instruction surface

### Per-tag skill files (`.clinerules/skills/`)

Cline should have one skill file per canonical tag, mirroring the structure used by Codex
and Claude.  Cline does not use YAML frontmatter in `.clinerules/` files, so plain markdown
is correct:

```text
.clinerules/
  skills/
    plan.md
    implement.md
    review.md
    audit.md
    check-in-prep.md
```

Each skill file must follow the shared Trigger / Do / Do not structure with Cline-specific
hook or workflow invocation notes appended.

### Hook configuration

Document or implement the Cline hook path that intercepts the first non-empty line and
resolves the canonical tag before the Cline workflow engine starts.  If Cline hooks are
feature-gated in the current version, document the fallback to the bridge wrapper explicitly
in the runbook and in this packet.

### Fallback bridge integration

The bridge (`tools/cline_prompt_trigger_bridge.py`) must remain the stable fallback path
when hooks are unavailable.  The `.clinerules/` files and bridge must produce identical
normalized request envelopes.

## Prompt-trigger exposure details

### User-facing flow

1. user types the tagged prompt into Cline chat or the Cline VS Code surface
2. a prompt hook (or the bridge as fallback) reads the first non-empty line and resolves
   the canonical action
3. `.clinerules/` doctrine, per-tag skill files, and workflow files apply the canonical
   review and tool policies
4. the normalized request is handed to the matching workflow or task mode

### Failure mode

If hook execution is unavailable, the shared bridge performs the same normalization.
Provider-specific workflow details stay isolated from the shared grammar docs.

## Prerequisites

- PKT-PRV-031 verified
- PKT-PRV-009 verified

## Implementation steps

1. Create `.clinerules/skills/` with one file per canonical tag (plan, implement, review,
   audit, check-in-prep) using the shared Trigger / Do / Do not structure
2. Document or implement the Cline hook configuration; if hooks are feature-gated, document
   the fallback-only path explicitly
3. Create or document Cline workflow files for each canonical tag if the Cline version
   supports them
4. Add smoke tests for `@plan` and `@review` via the Cline bridge
5. Verify CLI and VS Code surfaces produce the same normalized launch envelope

## Acceptance criteria

- `.clinerules/skills/` exists with all 5 canonical tag files
- each skill file uses the shared Trigger / Do / Do not structure
- hook configuration is either implemented or the fallback-only path is explicitly documented
- tagged Cline prompts reach the shared launcher path
- Cline rules do not redefine the canonical grammar
- smoke tests pass for at least `@plan` and `@review`

## Files to create or update

- `.clinerules/skills/plan.md`
- `.clinerules/skills/implement.md`
- `.clinerules/skills/review.md`
- `.clinerules/skills/audit.md`
- `.clinerules/skills/check-in-prep.md`
- Cline hook config (or documented fallback-only decision)
- `docs/implementation/providers/25_Cline_Prompt_Trigger_Runbook.md` — update with hook status
- Cline prompt-trigger smoke tests

## Rollback guidance

- revert `.clinerules/skills/` and hook config changes only
- leave `.clinerules/prompt-tags.md` and `.clinerules/review-policy.md` untouched
- leave the shared launch grammar untouched
- the bridge tool remains in place
