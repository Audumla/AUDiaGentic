# PKT-FND-010 — Repository inventory, migration map, and ambiguity report

**Phase:** Phase 0.3  
**Status:** VERIFIED  
**Owner:** Foundations  
**Scope:** workspace

## Goal

Inventory the current repository, map existing modules into the target domains, and document ambiguous or mixed-responsibility areas before code moves begin.

## Dependencies

- current baseline verified
- `49_Repository_Domain_Refactor_and_Package_Realignment.md` in place

## Owns

- migration map document
- ambiguity report for mixed-responsibility modules
- first-pass old-path -> target-domain mapping

## Required outputs

- `docs/implementation/refactor/phase-0-3/repository-inventory.md`
- `docs/implementation/refactor/phase-0-3/migration-map.md`
- `docs/implementation/refactor/phase-0-3/ambiguity-report.md`
- `docs/implementation/refactor/phase-0-3/public-import-surface.md`

## Minimum inventory scope

At minimum classify:

- `src/audiagentic/contracts`
- `src/audiagentic/lifecycle`
- `src/audiagentic/release`
- `src/audiagentic/jobs`
- `src/audiagentic/providers`
- `src/audiagentic/server`
- `src/audiagentic/channels/discord`
- `tools/`
- `tests/`
- `src/audiagentic/contracts/schemas/`
- `docs/examples/`
- managed baseline assets including `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules*`, `.claude/`, `.agents/skills/`, and `.github/workflows/`

For each inventory row include:

- current path
- current purpose
- dominant responsibility
- secondary responsibility
- proposed target domain
- public import affected: yes/no
- baseline or install impact: yes/no
- notes

## Ambiguity report shape

For each mixed-responsibility area record:

- current path
- dominant responsibility
- secondary responsibility
- target domain recommendation
- whether to split or keep together in the first pass
- whether a compatibility shim is likely to be needed

Expected hotspots include:

- prompt-trigger and bridge code spanning jobs, providers, and tooling
- stream/input/completion logic spanning jobs and provider adapters
- provider instruction assets versus install-baseline handling
- `docs/examples/` and `src/audiagentic/contracts/schemas/` ownership

## Public import surface output

`public-import-surface.md` must enumerate:

- import paths that must be preserved through shims because they are referenced by tracked docs, examples, workflows, install/bootstrap assets, tool entrypoints, or explicit documented import examples
- internal-only imports that should simply be rewritten during the move

## Baseline impact discovery

The inventory or a clearly linked section must identify paths that affect:

- installable baseline assets
- provider instruction assets
- managed workflows
- exclusion of `.audiagentic/runtime/**`
- release bootstrap path resolution

## Acceptance criteria

- major modules/folders are classified into canonical domains
- mixed-responsibility hotspots are explicitly listed
- refactor notes capture unresolved ambiguity instead of hiding it
- no broad code-motion question remains hidden in prose
- public import surface is explicitly enumerated
- baseline-sensitive paths are explicitly identified
