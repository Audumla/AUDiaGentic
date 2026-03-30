# PKT-PRV-012 — Provider model catalog + selection rules

**Phase:** Phase 4.1  
**Primary owner group:** Providers

## Goal

Introduce provider model catalog support and deterministic model selection rules so teams can switch models easily while keeping runtime behavior explicit and traceable.

## Why this packet exists now

Providers change model availability over time. Without an explicit catalog and selection contract, configuration drift will cause silent runtime failures and inconsistent job outputs. Phase 4.1 adds a stable seam for model discovery and selection without rewriting Phase 4 provider adapters.

## Dependencies

- `PKT-PRV-011`

## Concrete provider model inputs

This packet must support and normalize the following fields:

- provider config `default-model`
- provider config `model-aliases`
- provider config `catalog-refresh`
- job request `model-id`
- job request `model-alias`
- runtime catalog `provider-id`
- runtime catalog `models[].model-id`

## Ownership boundary

This packet owns the following implementation surface:

- `docs/specifications/architecture/24_DRAFT_Provider_Model_Catalog_and_Selection.md`
- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/schemas/provider-model-catalog.schema.json`
- `docs/examples/fixtures/provider-model-catalog.valid.json`
- `docs/examples/fixtures/provider-model-catalog.invalid.json`
- `docs/examples/project-scaffold/.audiagentic/providers.yaml.example`
- `src/audiagentic/providers/catalog.py`
- `src/audiagentic/providers/models.py`
- `src/audiagentic/providers/health.py`
- `src/audiagentic/providers/selection.py`
- `tools/refresh_model_catalog.py`
- `tests/unit/providers/test_model_catalog.py`
- `tests/integration/providers/test_model_selection.py`
- `tests/unit/contracts/test_schema_validation.py`
- provider docs under `docs/specifications/architecture/providers/`

### It may read from
- frozen contracts in `docs/specifications/architecture/`
- approved fixtures under `docs/examples/fixtures/`
- outputs from dependency packets only

### It must not edit directly
- files owned by other groups unless a dependency explicitly requires it
- tracked release docs outside the owned writer module
- contract schemas unless this packet is in the contracts ownership chain

## Public contracts used

- provider config and selection contracts in `03_Common_Contracts.md`
- draft model catalog spec in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`
- phase gates from `02_Phase_Gates_and_Exit_Criteria.md`

## Detailed build steps

1. Finalize the model catalog contract and add the provider-model-catalog schema.
2. Add fixtures for valid and invalid model catalogs and wire into schema validation.
3. Extend provider config to include `model-aliases` and `catalog-refresh` fields.
4. Implement model catalog read/write helpers under `src/audiagentic/providers/catalog.py`.
5. Implement model resolution logic under `src/audiagentic/providers/models.py`.
6. Update provider selection to validate resolved model against catalog when present.
7. Add `tools/refresh_model_catalog.py` CLI to write runtime catalogs.
8. Update provider docs with model catalog guidance and examples.
9. Publish the provider/model contract and examples so `PKT-JOB-007` can consume them without redefining field names.
10. Run schema, unit, and integration tests listed below.

## Integration points

- `src/audiagentic/providers/registry.py`
- `src/audiagentic/providers/selection.py`
- `src/audiagentic/providers/health.py`
- `src/audiagentic/jobs/packet_runner.py`
- `src/audiagentic/jobs/records.py`
- `tools/seed_example_project.py`
- `tools/validate_schemas.py`
- `tests/integration/providers/test_selection.py`
- `tests/integration/test_example_scaffold.py`

## Model selection rules (must be deterministic)

Resolution order:
1. job request `model-id`
2. job request `model-alias`
3. provider config `default-model`
4. fail validation if none resolve

If a catalog exists:
- resolved model must exist in catalog
- catalog staleness should warn but not block in MVP

## Tests to add

- schema validation for provider-model-catalog fixtures
- unit tests for catalog load/write and validation errors
- integration tests for model selection resolution and alias handling

## Acceptance criteria

- model catalog contract, schema, and fixtures are added and validated
- model selection resolves explicit id, alias, and default deterministically
- catalog refresh CLI writes runtime catalog atomically
- provider docs reflect model catalog and selection rules
- job and provider seams agree on the same model metadata fields

## Recovery procedure

If this packet fails mid-implementation:
- revert schema and fixture changes in `docs/schemas/` and `docs/examples/fixtures/`
- delete any partially written runtime catalogs under `.audiagentic/runtime/providers/`
- revert provider selection and health changes
- rerun `python -m pytest tests/unit/contracts/test_schema_validation.py tests/unit/providers/test_model_catalog.py tests/integration/providers/test_model_selection.py`

## Parallelization note

This packet may run in parallel only after all dependencies are merged and only with packets whose ownership boundary does not overlap this packet.

## Out of scope

- automatic model failover across providers
- dynamic model scoring or benchmarking
- forcing catalog refresh inside job execution
