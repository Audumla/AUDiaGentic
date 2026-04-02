# Phase 0.3 — Repository Domain Refactor and Package Realignment

## Purpose

Execute the repository-wide structural refactor before further feature implementation continues so later work lands on the maintained domain-oriented structure rather than the legacy layout.

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

## Acceptance criteria

- the target structure and domain boundaries are frozen before broad code motion begins
- the installable baseline model remains intact through the refactor
- imports/build/test configuration are updated consistently
- old/new path mapping is documented
- further non-refactor implementation work is paused until the refactor checkpoint completes

## Current intent

This phase is a controlled structural correction, not a feature expansion. It should be treated as a prerequisite checkpoint before continuing Phase 1.4 implementation or later provider/runtime build work.
