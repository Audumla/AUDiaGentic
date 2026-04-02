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

### 2. Compatibility and migration policy

The refactor must state:
- whether temporary compatibility shims are allowed
- whether old import paths remain for one transition phase
- how stale paths are detected and removed
- when code may stop importing from old locations

### 3. Deterministic script/tool placement

The brief names `apps/` and `packages/`, but current AUDiaGentic also relies on deterministic scripts and repo utilities under `tools/`.

This phase must explicitly define whether:
- `tools/` remains as a deterministic utility root
- selected tools move into `apps/`
- both coexist during migration

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

### 6. Test layout strategy

The refactor must define whether tests stay centralized under `/tests` with mirrored domain structure or become partially domain-local.

The initial requirement is to preserve the current centralized test root unless there is a strong reason to change it.

### 7. Cross-domain dependency rules

The refactor must add explicit allowed dependency directions so the new domains do not immediately leak into one another.

At minimum:
- `scoping` must not directly own `runtime` or `channels`
- `execution` may depend on `contracts`, `core`, and selected `runtime` ports, but not directly on channel formatting logic
- `streaming` may bridge `execution`, `runtime`, and `channels`, but must not become the home of telemetry storage
- `observability` must remain distinct from live interaction flow

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
4. code moves and module splits
5. import repair and compatibility shims
6. terminology cleanup
7. docs/test/build-config cleanup
8. final validation

## Dependencies

- `02_Core_Boundaries_and_Dependency_Rules.md`
- `03_Common_Contracts.md`
- `03_Target_Codebase_Tree.md`
- `05_Module_Ownership_and_Parallelization_Map.md`
- `48_Installable_Project_Baseline_and_Managed_Asset_Synchronization.md`

## Notes

This phase is intentionally placed before further non-refactor implementation work. The goal is to prevent the repository from accumulating more functionality on top of a structure that is about to move.
