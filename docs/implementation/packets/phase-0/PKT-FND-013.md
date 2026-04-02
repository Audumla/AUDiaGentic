# PKT-FND-013 — Documentation, tests, and validation cleanup after refactor

**Phase:** Phase 0.3  
**Status:** WAITING_ON_DEPENDENCIES  
**Owner:** Foundations + Docs  
**Scope:** workspace

## Goal

Finish the refactor by cleaning docs, tests, configuration paths, and validation notes so the new structure is the only documented current shape.

## Dependencies

- `PKT-FND-012` VERIFIED

## Must leave behind

- updated architecture docs
- updated repository structure docs
- refactor notes and migration map
- validation/build/test notes
- `docs/implementation/refactor/phase-0-3/final-validation-report.md`
- no active docs describing the old structure as current

## Final validation report must include

- what moved
- what is still shimmed
- what legacy imports remain and why
- what failed and is deferred
- whether the installable baseline model remained intact

## Acceptance criteria

- refactor mapping and refactor notes exist
- docs, tests, and build references use the new structure consistently
- the repository is ready for post-refactor implementation work
