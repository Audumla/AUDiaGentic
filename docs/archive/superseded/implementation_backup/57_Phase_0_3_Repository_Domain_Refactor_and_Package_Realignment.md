# Phase 0.3 — Repository Domain Refactor and Package Realignment

## Purpose

Execute the repository-wide structural refactor before further feature implementation continues so later work lands on the maintained domain-oriented structure rather than the legacy layout.

## Checkpoint model

Treat this phase as a strict two-part checkpoint:

1. decision freeze and inventory
2. code/package moves only after the freeze is verified

The enforced order is:

1. `PKT-FND-010` — discovery only
2. `PKT-FND-011` — structural decision freeze
3. `PKT-FND-012` — code/package movement under frozen rules
4. `PKT-FND-013` — cleanup, validation, and old-structure removal

Do not start broad repository code motion until `PKT-FND-011` is verified.

## Read before starting

- `docs/specifications/architecture/49_Repository_Domain_Refactor_and_Package_Realignment.md`
- `docs/specifications/architecture/02_Core_Boundaries_and_Dependency_Rules.md`
- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/specifications/architecture/04_Project_Layout_and_Local_State.md`
- `docs/specifications/architecture/48_Installable_Project_Baseline_and_Managed_Asset_Synchronization.md`
- `docs/implementation/03_Target_Codebase_Tree.md`
- `docs/implementation/05_Module_Ownership_and_Parallelization_Map.md`
- `docs/implementation/20_Packet_Dependency_Graph.md`
- `docs/implementation/31_Build_Status_and_Work_Registry.md`

## Packet scope

- repository inventory and migration map
- target tree/ownership/dependency freeze for the new domains
- package/import strategy and compatibility-shim rules
- code/package/app moves and module splits
- docs, tests, build-config, and path validation after the move

## Frozen decisions for this checkpoint

- use a domain-oriented reorganization under `src/audiagentic/`
- preserve stable public Python imports with temporary compatibility shims
- keep `tools/` as the deterministic repo utility root
- keep `src/audiagentic/contracts/schemas/` and `docs/examples/` in place for this tranche
- keep centralized `tests/` and mirror the new domain structure inside it
- require explicit cross-domain dependency directions before code motion

## Refactor artifacts

This phase should write its working artifacts under:

- `docs/implementation/refactor/phase-0-3/repository-inventory.md`
- `docs/implementation/refactor/phase-0-3/migration-map.md`
- `docs/implementation/refactor/phase-0-3/ambiguity-report.md`
- `docs/implementation/refactor/phase-0-3/public-import-surface.md`
- `docs/implementation/refactor/phase-0-3/final-validation-report.md`

Use the templates in `docs/implementation/refactor/phase-0-3/*.template.md` when creating the live artifacts.

## Support scripts expected before broad code motion

`PKT-FND-012` should begin by putting deterministic refactor helpers in place:

- `tools/inventory_imports.py`
- `tools/check_cross_domain_imports.py`
- `tools/find_legacy_paths.py`
- `tools/check_baseline_assets.py`
- `tools/refactor_smoke.py`

These scripts reduce the amount of manual reasoning needed during the move and keep the refactor aligned with the project's script-first doctrine.

## Baseline preservation smoke matrix

`final-validation-report.md` should explicitly record the outcome of:

- baseline asset inventory still resolves correctly
- `.audiagentic/runtime/**` remains excluded from install-baseline behavior
- provider instruction assets remain locatable from the managed baseline
- managed workflow asset paths still resolve correctly
- example project seeding still resolves the expected managed baseline paths

## What PKT-FND-011 must freeze before PKT-FND-012 starts

- the real post-refactor target tree in `03_Target_Codebase_Tree.md`
- the real post-refactor ownership map in `05_Module_Ownership_and_Parallelization_Map.md`
- the canonical repository-domain dependency rules in `02_Core_Boundaries_and_Dependency_Rules.md`
- the public import surface and shim scope
- the placement of `nodes`, `discovery`, `federation`, and `connectors` relative to the main repository-domain model

## Acceptance criteria

- the target structure and domain boundaries are frozen before broad code motion begins
- the installable baseline model remains intact through the refactor
- imports/build/test configuration are updated consistently
- old/new path mapping is documented
- further non-refactor implementation work is paused until the refactor checkpoint completes

## Recommended execution slices inside PKT-FND-012

- Slice 12A — create target scaffolding and shim placeholders
- Slice 12B — move pure/shared code first
- Slice 12C — move lifecycle/release shared internals
- Slice 12D — move jobs / execution / runtime seams
- Slice 12E — move channels / streaming / observability

Run refactor smoke, legacy-path checks, and cross-domain dependency checks after every slice.

## Suggested branch or worktree plan

- `phase-0-3-fnd-010-inventory`
- `phase-0-3-fnd-011-freeze`
- `phase-0-3-fnd-012-refactor`
- `phase-0-3-fnd-013-cleanup`

These branches or worktrees are sequential, not parallel:

- `011` branches from `010`
- `012` branches from `011`
- `013` branches from `012`
- they merge in order

After that checkpoint completes, resume:

- `phase-1-4-baseline-sync`

## Current intent

This phase is a controlled structural correction, not a feature expansion. It should be treated as a prerequisite checkpoint before continuing Phase 1.4 implementation or later provider/runtime build work.

## Stop-if rules

Stop and return to decision work if:
- the package strategy cannot be decided cleanly
- the canonical src/audiagentic/contracts/schemas/examples placement cannot be decided cleanly
- cross-domain dependency directions remain ambiguous
- the installable baseline model breaks without new policy
- the move requires hidden feature redesign instead of structural movement
- the old structure cannot be removed from current docs by the cleanup packet
