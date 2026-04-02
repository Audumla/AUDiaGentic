# Repository Domain Refactor and Package Realignment

## Status

Implementation-ready structural refactor spec.

## Purpose

Define the structural refactor that reorganizes the repository around explicit platform domains before further feature implementation continues.

This refactor is a repository-structure and ownership correction. It is intended to improve maintainability and separation of concerns without changing the platform's functional intent.

## Why this phase exists

The current repository has accumulated multiple later features on top of an earlier layout. The existing structure is still serviceable, but it is no longer the clearest long-term shape for:
- scoping versus execution
- runtime integrations versus human channels
- streaming versus observability
- installable baseline assets versus runtime state

This phase freezes the structural target and migration rules before more code is added.

## Execution model

Treat this phase as a two-part checkpoint:

1. decision freeze and inventory
2. code/package moves only after the freeze is complete

The packet execution order is therefore strict:

1. `PKT-FND-010`
2. `PKT-FND-011`
3. `PKT-FND-012`
4. `PKT-FND-013`

Do not start broad repository code motion before `PKT-FND-011` is verified.

Broad code motion for this checkpoint means:
- any move, rename, or import rewrite inside `src/audiagentic/` that changes canonical module ownership or public/internal import paths

Not broad code motion for this checkpoint:
- docs-only updates
- support scripts
- inventory and freeze artifacts
- target scaffolding and empty shim placeholders created under the frozen plan

## Scope

This phase covers:
- repository-level domain mapping
- target folder/package layout
- ownership realignment
- import and compatibility strategy
- documentation and terminology normalization
- build/test/config path updates required by the moves

## Non-goals

- adding new product behavior
- redesigning stable runtime protocols unless required by the move
- expanding feature scope beyond what is needed to complete the refactor
- changing install semantics except where path realignment requires it

## Canonical top-level domains

The repository should converge on these top-level platform domains:
- `scoping`
- `execution`
- `runtime`
- `channels`
- `streaming`
- `observability`
- `core`
- `contracts`
- `config`

## Required clarifications added by this phase

The refactor brief direction is good, but the following decisions must be explicit before code moves begin.

### 1. Package/import strategy

This repo is currently Python-first and centered on `src/audiagentic/...`.

Before moving code, the refactor must explicitly choose whether the target shape is:
- a literal top-level monorepo with `/apps` and `/packages`, or
- a domain-oriented reorganization nested under the existing Python package root while preserving packaging ergonomics

For this phase, the refactor contract must preserve a stable public Python import path for AUDiaGentic unless a deliberate migration shim strategy is written down.

Frozen decision for this checkpoint:
- use a domain-oriented reorganization under `src/audiagentic/`
- do not convert the repository into a literal top-level `/apps` + `/packages` monorepo in this tranche
- preserve stable public Python import paths with compatibility shims during the transition

Public import surface for this checkpoint:
- any import path explicitly referenced by tracked docs, examples, workflows, install/bootstrap assets, or provider instruction assets
- stable package-facing paths intentionally used by repo-owned entry points and external project setup guidance

Internal-only import surface for this checkpoint:
- leaf modules not referenced by tracked docs, workflows, install/bootstrap assets, or cross-project guidance
- test-only imports and one-off script-local imports

Shim rule for this checkpoint:
- moved public import paths require compatibility shims during the transition window
- internal-only paths may be rewritten directly once the migration map is frozen

### 2. Compatibility and migration policy

The refactor must state:
- whether temporary compatibility shims are allowed
- whether old import paths remain for one transition phase
- how stale paths are detected and removed
- when code may stop importing from old locations

Frozen decision for this checkpoint:
- temporary compatibility shims are allowed
- old import paths may remain for one structural checkpoint
- stale paths must be detectable mechanically
- no new code may be added against legacy paths once `PKT-FND-012` begins
- stale import cleanup belongs to `PKT-FND-013`

### 3. Deterministic script/tool placement

The brief names `apps/` and `packages/`, but current AUDiaGentic also relies on deterministic scripts and repo utilities under `tools/`.

This phase must explicitly define whether:
- `tools/` remains as a deterministic utility root
- selected tools move into `apps/`
- both coexist during migration

Frozen decision for this checkpoint:
- keep `tools/` as the repository-visible deterministic utility root
- move shared reusable logic into `src/audiagentic/...` where appropriate
- keep tool entry points thin

### 4. Installable baseline preservation

The refactor must preserve the new Phase 1.4 installable-baseline model.

That means the refactor must explicitly account for:
- tracked `.audiagentic/` baseline assets
- provider instruction assets such as `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules/`, `.claude/`, and `.agents/skills/`
- managed workflow assets under `.github/workflows/`
- exclusion of `.audiagentic/runtime/**` from install baseline behavior

### 5. Contracts and schemas location

The brief proposes top-level `/schemas` and `/examples`, while the current repo uses `docs/schemas/` and `docs/examples/`.

The refactor must explicitly decide whether those become:
- true top-level roots, or
- remain under `docs/` with updated internal ownership only

Frozen decision for this checkpoint:
- keep `docs/schemas/` and `docs/examples/` canonical in this tranche
- do not move them to top-level roots during the same tranche as the package refactor

### 6. Test layout strategy

The refactor must define whether tests stay centralized under `/tests` with mirrored domain structure or become partially domain-local.

The initial requirement is to preserve the current centralized test root unless there is a strong reason to change it.

Frozen decision for this checkpoint:
- keep centralized `tests/`
- mirror the new domain structure inside `tests/`
- do not introduce mixed domain-local tests during this refactor tranche

### 7. Cross-domain dependency rules

The refactor must add explicit allowed dependency directions so the new domains do not immediately leak into one another.

At minimum:
- `scoping` must not directly own `runtime` or `channels`
- `execution` may depend on `contracts`, `core`, and selected `runtime` ports, but not directly on channel formatting logic
- `streaming` may bridge `execution`, `runtime`, and `channels`, but must not become the home of telemetry storage
- `observability` must remain distinct from live interaction flow

Frozen dependency directions for this checkpoint:
- `contracts` may be imported by every domain
- `core` may be imported by every domain; `tests/` and `tools/` should prefer stable APIs
- `config` may be imported by `execution`, `runtime`, `channels`, `streaming`, and `observability`
- `scoping` may depend on `contracts`, `core`, and `config`
- `execution` may depend on `contracts`, `core`, `config`, selected `runtime` ports, and selected `streaming` ports/adapters
- `runtime` may depend on `contracts`, `core`, and `config`
- `channels` may depend on `contracts`, `core`, `config`, selected presentation-facing runtime records, and selected execution entrypoints/facades
- `streaming` may depend on `execution`, `runtime`, `channels`, `contracts`, and `core`
- `observability` may depend on `runtime`, `contracts`, `core`, and `config`

Forbidden dependency directions for this checkpoint:
- `scoping -> channels`
- `scoping -> observability`
- `execution ->` channel formatting or rendering internals
- `observability ->` live interaction control
- `channels ->` execution internals beyond approved entrypoint/facade seams
- `runtime -> channels`

## Extension-root placement

The later optional extension roots:
- `nodes`
- `discovery`
- `federation`
- `connectors`

remain reserved top-level extension roots under `src/audiagentic/` during this tranche.

For this checkpoint:
- do not collapse them into the main repository-domain taxonomy
- do not let them redefine the primary repository-domain ownership model
- treat them as parallel reserved extension seams that may align conceptually with `runtime`, `channels`, `streaming`, or `observability` later without changing their reserved root paths now

## Canonical object model alignment

The repository should converge on the following vocabulary:
- Request
- Scope
- Plan
- Task
- WorkPackage
- Job
- Run
- Agent
- Session
- Thread
- Artifact
- Event

This phase does not require reckless bulk renaming. It requires the migration plan to identify where terms are currently blurred and how the repo will converge safely.

## Structural rules

- Do not merge `runtime` and `channels`.
- Do not merge `streaming` and `observability`.
- Do not merge `scoping` and `execution`.
- Avoid vague catch-all roots such as `management`, `integrations`, `misc`, or `shared` when a canonical domain exists.
- Keep app entry points thin; business logic belongs in packages/modules.
- Preserve behavior unless a documented structural blocker requires change.

## Required inventory outputs

`PKT-FND-010` must create and maintain:
- `docs/implementation/refactor/phase-0-3/repository-inventory.md`
- `docs/implementation/refactor/phase-0-3/migration-map.md`
- `docs/implementation/refactor/phase-0-3/ambiguity-report.md`
- `docs/implementation/refactor/phase-0-3/public-import-surface.md`

`PKT-FND-013` must also create:
- `docs/implementation/refactor/phase-0-3/final-validation-report.md`

The inventory must at minimum classify:
- `src/audiagentic/contracts`
- `src/audiagentic/lifecycle`
- `src/audiagentic/release`
- `src/audiagentic/jobs`
- `src/audiagentic/providers`
- `src/audiagentic/server`
- `src/audiagentic/channels/discord`
- `tools/`
- `tests/`
- `docs/schemas/`
- `docs/examples/`
- managed baseline assets such as `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules*`, `.claude/`, `.agents/skills/`, and `.github/workflows/`

Each ambiguity record should capture:
- current path
- dominant responsibility
- secondary responsibility
- target domain recommendation
- split-or-keep recommendation for the first pass
- whether a compatibility shim is required

Expected hotspots include:
- prompt-trigger and bridge code spanning jobs, providers, and tooling
- stream/input/completion logic spanning jobs and provider adapters
- provider instruction assets versus install-baseline handling
- `docs/examples/` and `docs/schemas/` ownership

## Support scripts required before broad code motion

Before broad code/package movement in `PKT-FND-012`, the refactor should add deterministic helper scripts for:
- `tools/inventory_imports.py`
- `tools/check_cross_domain_imports.py`
- `tools/find_legacy_paths.py`
- `tools/check_baseline_assets.py`
- `tools/refactor_smoke.py`

These scripts should own repetitive scan/check/smoke behavior so the refactor remains script-first and low-risk.

Minimum support-script contract for this checkpoint:

| Script | Primary owner | Minimum output | Failure behavior | Required cadence |
|---|---|---|---|---|
| `tools/inventory_imports.py` | `PKT-FND-012` | import inventory grouped by current path/domain | non-zero exit on unreadable files or unresolved internal imports | before first broad code motion and after every move slice |
| `tools/check_cross_domain_imports.py` | `PKT-FND-012` | explicit pass/fail against frozen dependency directions | non-zero exit on forbidden dependency edges | after every move slice and at final validation |
| `tools/find_legacy_paths.py` | `PKT-FND-012` | list of stale imports and legacy paths across code/docs/tests/tools | non-zero exit when required scan roots cannot be processed | after every move slice and at final validation |
| `tools/check_baseline_assets.py` | `PKT-FND-012` | pass/fail report for installable baseline asset visibility and runtime exclusions | non-zero exit on missing managed baseline assets or runtime-exclusion violations | after lifecycle/release moves, after channels/streaming moves, and at final validation |
| `tools/refactor_smoke.py` | `PKT-FND-012` | aggregate smoke report for imports, lifecycle, release bootstrap, and schema/example paths | non-zero exit on smoke failure | after every move slice and at final validation |

## Required outputs from the refactor

The refactor must leave behind:
- a migration map from old paths to new paths
- updated target tree and ownership map
- updated dependency rules for the new domains
- updated architecture docs describing repository structure and domain boundaries
- explicit notes on compatibility shims, if any
- build/test validation notes

## Recommended implementation order

1. inventory and path mapping
2. target tree + ownership + dependency freeze
3. package/import strategy freeze
4. support-script and checker preparation
5. code moves and module splits
6. import repair and compatibility shims
7. terminology cleanup
8. docs/test/build-config cleanup
9. final validation

Recommended internal slices for `PKT-FND-012`:
- Slice 12A: create target scaffolding and compatibility-shim placeholders
- Slice 12B: move pure/shared code first (`contracts`, low-level `core`, stable `config`)
- Slice 12C: move lifecycle/release shared internals
- Slice 12D: move jobs / execution / runtime seams
- Slice 12E: move channels / streaming / observability

Run smoke and legacy-path checks after every slice.

## Dependencies

- `02_Core_Boundaries_and_Dependency_Rules.md`
- `03_Common_Contracts.md`
- `03_Target_Codebase_Tree.md`
- `05_Module_Ownership_and_Parallelization_Map.md`
- `48_Installable_Project_Baseline_and_Managed_Asset_Synchronization.md`

## Notes

This phase is intentionally placed before further non-refactor implementation work. The goal is to prevent the repository from accumulating more functionality on top of a structure that is about to move.

Stop the refactor immediately if:
- `PKT-FND-011` cannot decide the package strategy
- `PKT-FND-011` cannot decide canonical docs/schemas/examples placement
- `PKT-FND-011` cannot define allowed dependency directions cleanly
- `PKT-FND-012` reveals the installable baseline model breaks without more policy
- `PKT-FND-012` requires hidden feature redesign rather than structural movement
- `PKT-FND-013` cannot make the old structure disappear from current docs cleanly
