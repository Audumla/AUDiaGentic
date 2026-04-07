# PKT-FND-008 — Incremental contract/schema updates

**Phase:** Phase 0.1  
**Primary owner group:** Contracts

## Goal

Capture post-Phase 0 contract and schema updates required by later phases while keeping Phase 0 validation guarantees intact.

## Why this packet exists now

Later phases may introduce new contract fields or schemas that must be validated by the Phase 0 tooling. This packet provides a controlled entry point for those incremental updates without reopening Phase 0 core design work.

## Dependencies

- Phase 0 gate `VERIFIED`
- contract inputs from `PKT-PRV-011` and `PKT-PRV-012`

## Concrete contract inputs

This packet is expected to finalize and validate the following fields and schema shapes:

- `ProviderConfig.access-mode`
- `ProviderConfig.auth-ref`
- `ProviderConfig.default-model`
- `ProviderConfig.model-aliases`
- `ProviderConfig.catalog-refresh`
- `ProviderModelCatalog.provider-id`
- `ProviderModelCatalog.fetched-at`
- `ProviderModelCatalog.source`
- `ProviderModelCatalog.models[]`
- job metadata fields used by later phases: `model-id`, `model-alias`

## Ownership boundary

This packet owns the following implementation surface:

- `docs/specifications/architecture/03_Common_Contracts.md`
- `src/audiagentic/contracts/schemas/*` (new or updated schemas)
- `docs/examples/fixtures/*` (fixtures for new schemas)
- `tools/validate_schemas.py`
- `tests/unit/contracts/test_schema_validation.py`

### It may read from
- later-phase packets that introduce new contract fields
- existing schema/fixture tooling

### It must not edit directly
- lifecycle, release, job, provider, or overlay modules
- tracked release docs outside the release ownership boundary

## Detailed build steps

1. Collect the finalized contract deltas from `PKT-PRV-011` and `PKT-PRV-012`.
2. Update `03_Common_Contracts.md` with the exact field names and validation rules.
3. Add or update schemas under `src/audiagentic/contracts/schemas/` for each concrete contract shape.
4. Add valid and invalid fixtures under `docs/examples/fixtures/` for each schema.
5. Update schema validation tooling if a new schema family requires lookup changes.
6. Ensure the example scaffold and validation tests reference the exact field set.
7. Run schema validation tests and verify fixture coverage.

## Integration points

- `docs/examples/project-scaffold/.audiagentic/providers.yaml.example`
- `tests/integration/test_example_scaffold.py`
- `tests/e2e/lifecycle/test_fresh_install.py`
- `tests/unit/contracts/test_schema_validation.py`

## Tests to add or update

- `tests/unit/contracts/test_schema_validation.py`
- any new schema fixtures validate or fail as expected

## Acceptance criteria

- new schemas and fixtures validate in CI
- contract updates are reflected in `03_Common_Contracts.md`
- the documented fields match the follow-on packets that consume them
- no changes to non-contract modules outside the ownership boundary

## Recovery procedure

If this packet fails mid-implementation:
- revert edits to `03_Common_Contracts.md`
- revert new or updated schemas and fixtures
- rerun `python -m pytest tests/unit/contracts/test_schema_validation.py`

## Parallelization note

This packet may run in parallel only with work that does not touch shared contracts or schemas.

## Out of scope

- implementing behavior changes in lifecycle, release, jobs, or providers
- adding new provider adapters
