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
- deterministic refactor support scripts and checkers
- code moves into target domains
- import rewrites and cycle cleanup
- preservation of public packaging expectations unless explicitly migrated

## First internal slice

Before broad code movement, add:

- `tools/inventory_imports.py`
- `tools/check_cross_domain_imports.py`
- `tools/find_legacy_paths.py`
- `tools/check_baseline_assets.py`
- `tools/refactor_smoke.py`

These tools should make the refactor mechanically checkable instead of relying on manual review alone.

## Recommended internal move slices

- Slice 12A — create target scaffolding and `__init__.py` files, plus shim placeholders
- Slice 12B — move pure/shared code first (`contracts`, low-level `core`, stable `config`)
- Slice 12C — move lifecycle/release shared internals
- Slice 12D — move jobs / execution / runtime seams
- Slice 12E — move channels / streaming / observability

During every slice:

- rewrite imports
- keep promised shim coverage
- run refactor smoke
- update the migration map

## Acceptance criteria

- core modules are moved into the frozen target structure
- build/test entry points still function or failures are explicitly documented
- stale import paths are either removed or covered by temporary shims
