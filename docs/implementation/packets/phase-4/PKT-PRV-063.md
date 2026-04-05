# PKT-PRV-063 — Template installation and managed surface contract (spec 50)

**Phase:** Phase 4.4.1
**Status:** READY_FOR_REVIEW
**Owner:** Infrastructure

## Objective

Document the contract between AUDiaGentic (the template) and a target project (the
consumer). A target-project developer must be able to read one document and know exactly
which files they own, which are managed, and what happens on the next sync.

Current reality:
- `docs/specifications/architecture/50_Template_Installation_and_Managed_Surface_Contract.md`
  now exists as the canonical contract draft for this packet
- managed headers are now stamped on generated provider surfaces
- `tools/check_baseline_assets.py --check-managed-headers` now exists
- `tools/regenerate_tag_surfaces.py` now reads canonical source through provider-owned
  renderers; the remaining work is to enforce the managed-surface contract in baseline
  validation and installation flows

## Problem

`baseline_sync.py` copies files into target projects with no documented contract. Target
developers cannot tell which files they may edit and which will be silently overwritten.
Managed files carry no marker. No CI check enforces that managed files are present and
unmodified.

## Scope

### 1. Architecture specification

**File:** `docs/specifications/architecture/50_Template_Installation_and_Managed_Surface_Contract.md`

Documents four sync modes with examples:

| Mode | Meaning | Example files |
|---|---|---|
| `required-managed` | AUDiaGentic owns; sync always overwrites | `.claude/skills/`, `.agents/skills/`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` |
| `create-if-missing` | AUDiaGentic seeds once; project owns after | `.audiagentic/project.yaml`, `.audiagentic/prompt-syntax.yaml` |
| `generated-managed` | Written at runtime; never hand-edit | `docs/releases/`, `.audiagentic/runtime/` artifacts |
| `runtime-only` | Never committed | `.audiagentic/runtime/` session state |

Spec must also document:
- How to request an override (open an issue / use a `create-if-missing` override file)
- That provider instruction/function surfaces are `required-managed` outputs of the shared
  regeneration facade (PKT-PRV-062) using provider-owned renderer definitions — editing the
  generated output directly will be overwritten on next regeneration

### 2. Managed-file headers

All `required-managed` template files must carry a top-of-file comment.

| File type | Comment style | Example |
|---|---|---|
| Markdown (`.md`) | HTML comment | `<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. Re-run regenerate_tag_surfaces.py to update. -->` |
| Python / YAML | hash comment | `# MANAGED_BY_AUDIAGENTIC: do not edit directly. Re-run regenerate_tag_surfaces.py to update.` |

Files to stamp:
- All files under `.claude/skills/`, `.agents/skills/`, `.clinerules/skills/`,
  `.gemini/commands/`, and future generated provider surfaces (provider-owned outputs)
- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` (instruction surfaces copied by baseline_sync)
- `.clinerules/prompt-tags.md`
- `.claude/rules/prompt-tags.md`

### 3. `check_baseline_assets.py` extension

Add `--check-managed-headers` flag that verifies that all `required-managed` files carry
the expected header. Exits non-zero with a list of missing/incorrect headers.

## Dependencies

- PKT-PRV-062 READY_FOR_REVIEW or better (defines which files are managed outputs)
- PKT-PRV-070 VERIFIED or better (canonical provider-function source established)

## Files to create or update

- `docs/specifications/architecture/50_Template_Installation_and_Managed_Surface_Contract.md`
- `tools/check_baseline_assets.py` — add `--check-managed-headers`
- `src/audiagentic/runtime/lifecycle/baseline_sync.py` — module docstring reference to spec 50

## Acceptance criteria

- spec 50 exists and covers all four sync modes with file examples
- a target-project developer can read spec 50 and know exactly which files they own
- all `required-managed` generated provider surface output files carry the managed header
- `check_baseline_assets.py --check-managed-headers` exits 0 on a clean repo and non-zero
  when a header is missing
