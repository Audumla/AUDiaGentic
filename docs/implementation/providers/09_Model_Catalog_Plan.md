# Provider Model Catalog and Selection Plan (Phase 4.1)

## Purpose

Provide a detailed implementation plan for provider model catalog support and deterministic model selection. This plan is a companion to `PKT-PRV-012`.

## Goals

- allow easy model switching per provider without changing job payloads
- ensure catalogs are refreshable, explicit, and stored under runtime state
- prevent silent failures when models are removed or renamed

## Key contracts and files

- Spec: `docs/specifications/architecture/24_DRAFT_Provider_Model_Catalog_and_Selection.md`
- Contract updates: `docs/specifications/architecture/03_Common_Contracts.md`
- Schema: `src/audiagentic/contracts/schemas/provider-model-catalog.schema.json`
- Runtime catalog: `.audiagentic/runtime/providers/<provider-id>/model-catalog.json`
- Config extensions: `.audiagentic/providers.yaml` additions for `model-aliases` and `catalog-refresh`

## Proposed data shapes

### ModelDescriptor
```json
{
  "model-id": "codex-pro",
  "display-name": "Codex Pro",
  "status": "active",
  "supports-structured-output": true,
  "context-window": 200000
}
```

### ProviderModelCatalog
```json
{
  "contract-version": "v1",
  "provider-id": "codex",
  "fetched-at": "2026-03-30T00:00:00Z",
  "source": "cli",
  "models": [ ... ]
}
```

## Implementation sequence

1. **Contract finalization**
   - lock draft contract into `03_Common_Contracts.md`
   - add schema and fixtures
2. **Catalog IO**
   - `src/audiagentic/config/provider_catalog.py`
   - helper functions:
     - `load_catalog(project_root, provider_id)`
     - `write_catalog(project_root, provider_id, payload)` (atomic)
     - `validate_catalog(payload)` (schema-backed)
3. **Model resolution**
   - `src/audiagentic/execution/providers/models.py`
   - `resolve_model(job_record, provider_cfg, catalog)` returns `{model-id, warnings}`
4. **Selection integration**
   - update `execution/providers/selection.py` to call resolution and validate against catalog
   - emit warnings when catalog is stale or missing
5. **CLI refresh**
   - `tools/refresh_model_catalog.py`
   - supports `--provider-id`, `--source`, `--json`
   - emits ErrorEnvelope on failure
6. **Provider docs**
   - add model catalog section to each provider document

## Catalog refresh strategy

- MVP uses explicit refresh only
- `catalog-refresh.max-age-hours` informs warnings only
- refresh sources:
  - `cli` for CLI-auth providers
  - `api` for direct HTTP providers
  - `static` for locally curated lists

## Tests

- `tests/unit/providers/test_model_catalog.py`
  - validates load/write, schema validation, atomic write
- `tests/integration/providers/test_model_selection.py`
  - resolves explicit model-id
  - resolves alias -> id
  - default-model fallback
  - rejects missing model when catalog present
- `tests/unit/contracts/test_schema_validation.py`
  - includes new fixtures

## Risk notes

- catalog drift between refreshes is expected; selection should warn but not block in MVP
- providers may return incompatible model names; normalize through `model-aliases`

## Success criteria

- catalogs are stored deterministically and validated
- model selection is explicit and testable
- job execution uses resolved model without changing existing job state shapes
