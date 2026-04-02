# PKT-FND-012 — Package/import strategy, compatibility shims, and code movement

**Phase:** Phase 0.3  
**Status:** WAITING_ON_DEPENDENCIES  
**Owner:** Foundations + Runtime  
**Scope:** workspace

## Goal

Perform the actual repository/package restructuring and import repair under a frozen migration strategy.

## Dependencies

- `PKT-FND-011` VERIFIED

## Must cover

- package/import strategy decision
- compatibility shim policy
- code moves into target domains
- import rewrites and cycle cleanup
- preservation of public packaging expectations unless explicitly migrated

## Acceptance criteria

- core modules are moved into the frozen target structure
- build/test entry points still function or failures are explicitly documented
- stale import paths are either removed or covered by temporary shims
