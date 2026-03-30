# PKT-LFC-008 — Incremental lifecycle updates for new config fields

**Phase:** Phase 1.1  
**Primary owner group:** Lifecycle

## Goal

Extend lifecycle validation and install/update behavior to support new config fields introduced by later phases without changing Phase 1 contract boundaries.

## Why this packet exists now

Later phases (for example provider model catalogs) may introduce new fields in tracked configs. Lifecycle must accept and validate those fields while preserving deterministic installation behavior.

## Dependencies

- Phase 1 gate `VERIFIED`
- `PKT-FND-008` for any schema updates required by new fields

## Concrete lifecycle inputs

This packet must recognize and preserve the new tracked config fields introduced by later phases:

- `.audiagentic/providers.yaml`
- `.audiagentic/project.yaml` if provider defaults or workflow selection are expressed there
- `.audiagentic/installed.json` if provider capability state is persisted there

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/lifecycle/*` (validation and install/update logic)
- lifecycle tests under `tests/unit/lifecycle/` and `tests/e2e/lifecycle/`

### It may read from
- updated contract schemas under `docs/schemas/`
- packet build sheets that introduce new config fields

### It must not edit directly
- contract schemas and fixtures (owned by `PKT-FND-008`)
- release, jobs, providers, or overlays

## Detailed build steps

1. Identify the concrete config fields requiring lifecycle validation from `PKT-FND-008`.
2. Update lifecycle validation to accept those fields without changing core semantics.
3. Ensure fresh install and update paths continue to write deterministic configs.
4. Preserve unknown-but-valid fields when lifecycle copies or rewrites project-local config.
5. Add tests that validate lifecycle behavior with the new fields present.

## Integration points

- `src/audiagentic/lifecycle/fresh_install.py`
- `src/audiagentic/lifecycle/update_dispatch.py`
- `src/audiagentic/lifecycle/cutover.py`
- `src/audiagentic/lifecycle/uninstall.py`
- `tests/integration/test_example_scaffold.py`
- `tests/e2e/lifecycle/test_fresh_install.py`

## Tests to add or update

- lifecycle validation tests for new config fields
- existing fresh install/update tests remain stable

## Acceptance criteria

- lifecycle validation accepts new fields and rejects invalid values
- no breaking changes to Phase 1 contract behavior
- deterministic lifecycle output remains unchanged for existing configs
- project-local config files keep the new fields intact across lifecycle operations

## Recovery procedure

If this packet fails mid-implementation:
- revert lifecycle changes
- rerun `python -m pytest tests/unit/lifecycle tests/e2e/lifecycle`

## Parallelization note

This packet may run in parallel only with work that does not modify lifecycle modules.

## Out of scope

- schema changes (owned by `PKT-FND-008`)
- provider selection or model catalog logic
