# PKT-PRV-070 — Canonical provider-function source migration

**Phase:** Phase 4.4.1
**Status:** VERIFIED
**Owner:** Infrastructure

## Objective

Establish `.audiagentic/skills/` as the single canonical generic source for provider-facing
function behavior. Migrate existing content from hand-authored provider surfaces into this
directory, then let provider-owned renderers generate provider-specific outputs. Remove
duplicate backward-compat skill folders. Mark all generated provider outputs as managed.

## Problem

Skill definitions are currently duplicated across:
- `.claude/skills/` (Claude Code surface)
- `.agents/skills/` (Codex CLI surface)

Both contain identical content except for the "Root surface" line — a clear sign they are
copies, not canonical sources. Additionally, backward-compat aliases (`audit/`, `review/`,
`plan/` etc.) exist alongside the new `ag-*` versions in both directories, creating
confusion about which is authoritative.

There is no single canonical generic source from which all provider surfaces are generated.
This packet creates that source.

## Scope

### 1. Create canonical provider-function source files

Create `.audiagentic/skills/<tag>/skill.md` for each canonical tag:

- `.audiagentic/skills/ag-plan/skill.md`
- `.audiagentic/skills/ag-implement/skill.md`
- `.audiagentic/skills/ag-review/skill.md`
- `.audiagentic/skills/ag-audit/skill.md`
- `.audiagentic/skills/ag-check-in-prep/skill.md`

Content is behavioural only — no provider-specific formatting, no "Root surface" line.
Format:

```markdown
---
name: ag-<tag>
description: <one-line description>
---

# ag-<tag> skill

Trigger:
- first non-empty line resolves to `ag-<tag>` or a configured alias

Do:
- ...

Do not:
- ...
```

Source: merge the current `.claude/skills/ag-*/SKILL.md` content (the more complete
version from previous session sync).

### 2. Hand the canonical source to the shared regeneration facade

After PKT-PRV-062 is implemented, run:

```
python tools/regenerate_tag_surfaces.py --project-root .
```

This regenerates `.claude/skills/`, `.agents/skills/`, `.clinerules/skills/`,
`.gemini/commands/`, and later provider surfaces from the canonical source through
provider-owned renderer definitions and stamps them with the managed header. The migration
packet only seeds the source/config and removes duplicate legacy folders; the facade refactor
and generated-output parity are owned by `PKT-PRV-062`.

### 3. Remove backward-compat duplicate skill folders

Current state: complete in the repo worktree. Keep this requirement here so the packet remains
auditable while `PKT-PRV-070` is still open for the downstream facade handoff.

Remove the following directories (legacy aliases — the tag grammar handles backward compat,
not duplicate skill files):

**`.claude/skills/`** — remove:
- `audit/` (duplicate of `ag-audit/`)
- `check-in-prep/` (duplicate of `ag-check-in-prep/`)
- `implement/` (duplicate of `ag-implement/`)
- `plan/` (duplicate of `ag-plan/`)
- `review/` (duplicate of `ag-review/`)

**`.agents/skills/`** — remove:
- `adhoc/` (should not be a skill; handled by parser)
- `audit/`, `check-in-prep/`, `implement/`, `plan/`, `review/` (same as above)

### 4. Update `prompt-syntax.yaml` surface config

Add a `skill-surfaces` section to `.audiagentic/prompt-syntax.yaml` that the shared facade
reads to know which provider renderer to invoke and where each provider's outputs belong:

```yaml
skill-surfaces:
  claude:
    renderer: claude
    path: .claude/skills/{tag}/SKILL.md
  codex:
    renderer: codex
    path: .agents/skills/{tag}/SKILL.md
  cline:
    renderer: cline
    path: .clinerules/skills/{tag}.md
  gemini:
    renderer: gemini
    path: .gemini/commands/{tag}.md
```

Provider-specific conversion logic must live with the provider, not inside one monolithic
shared script.

## Dependencies

- PKT-PRV-061 VERIFIED (canonical tag names in config)

## Files to create

- `.audiagentic/skills/ag-plan/skill.md`
- `.audiagentic/skills/ag-implement/skill.md`
- `.audiagentic/skills/ag-review/skill.md`
- `.audiagentic/skills/ag-audit/skill.md`
- `.audiagentic/skills/ag-check-in-prep/skill.md`
- `skill-surfaces` section in `.audiagentic/prompt-syntax.yaml`

## Files to delete

- `.claude/skills/audit/`, `check-in-prep/`, `implement/`, `plan/`, `review/`
- `.agents/skills/adhoc/`, `audit/`, `check-in-prep/`, `implement/`, `plan/`, `review/`

## Acceptance criteria

- `.audiagentic/skills/` contains one `skill.md` per canonical tag/function
- `skill-surfaces` configuration is placed in `.audiagentic/prompt-syntax.yaml` and can be
  read by the regeneration facade
- Backward-compat duplicate folders removed from `.claude/skills/` and `.agents/skills/`
- `python tools/regenerate_tag_surfaces.py --project-root . --check` exits 0 after duplicate
  outputs are removed from the generated surface map
- Target projects that receive these files via `baseline_sync` cannot break existing
  prompts (tag grammar aliases still resolve; only skill file locations change)

## Notes

- Do not delete the `ag-*` folders from `.claude/skills/` or `.agents/skills/` — those
  are valid managed outputs. Only remove the legacy unprefixed duplicates.
- The `adhoc/` folder in `.agents/skills/` is not a valid canonical tag skill; it
  should not exist. The generic-tag prompt is handled by the parser, not a skill file.
- This migration is the prerequisite for Cline (PKT-PRV-037) and Gemini (PKT-PRV-034)
  provider surfaces — both can be generated by the shared facade once this is done.
