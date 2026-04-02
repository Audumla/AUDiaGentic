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

## Must decide explicitly

- package/import strategy: domain-oriented reorganization under `src/audiagentic/`
- compatibility policy: temporary shims allowed for one structural checkpoint; no new code on legacy imports once `PKT-FND-012` begins
- deterministic tool placement: keep `tools/` as the utility root
- contracts/examples/schemas placement: keep `docs/schemas/` and `docs/examples/` in place for this tranche
- test strategy: keep centralized `tests/` and mirror the new domain structure inside it
- cross-domain dependency rules for `contracts`, `core`, `config`, `scoping`, `execution`, `runtime`, `channels`, `streaming`, and `observability`

## Must update

- `docs/implementation/03_Target_Codebase_Tree.md`
- `docs/implementation/05_Module_Ownership_and_Parallelization_Map.md`
- `docs/specifications/architecture/02_Core_Boundaries_and_Dependency_Rules.md`
- any overview doc that still describes the legacy structure as the intended target

## Exit condition before PKT-FND-012 may start

Do not start code/package movement until:

- one canonical target shape is documented
- dependency directions are explicit
- ownership maps match the target structure
- shim policy is written
- docs/examples/schemas placement is decided
- test layout strategy is decided

## Acceptance criteria

- one canonical repository target shape is documented
- allowed cross-domain dependencies are explicit
- ownership boundaries match the target structure
