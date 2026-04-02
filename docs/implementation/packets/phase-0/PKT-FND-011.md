# PKT-FND-011 — Target tree, ownership, and dependency freeze for domain refactor

**Phase:** Phase 0.3  
**Status:** WAITING_ON_DEPENDENCIES  
**Owner:** Foundations  
**Scope:** workspace

## Goal

Freeze the new repository target tree, ownership boundaries, and allowed dependency directions before the large code move starts.

## Dependencies

- `PKT-FND-010` VERIFIED

## Owns

- `docs/implementation/03_Target_Codebase_Tree.md`
- `docs/implementation/05_Module_Ownership_and_Parallelization_Map.md`
- `docs/specifications/architecture/02_Core_Boundaries_and_Dependency_Rules.md`
- related architecture overview and structure docs

## Acceptance criteria

- one canonical repository target shape is documented
- allowed cross-domain dependencies are explicit
- ownership boundaries match the target structure
