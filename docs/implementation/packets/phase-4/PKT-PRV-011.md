# PKT-PRV-011 — Provider access-mode contract + health config rules

**Phase:** Phase 4  
**Status:** VERIFIED
**Primary owner group:** Providers

## Goal

Add a provider `access-mode` to the provider config contract so the system can distinguish CLI-authenticated providers from env-key providers or unauthenticated local endpoints.

## Why this packet exists now

Provider access assumptions must be explicit before more providers and overlays are added. Without this contract, we cannot validate whether a provider should require an `auth-ref` or whether a locally installed CLI is expected to supply credentials.

## Dependencies

- `PKT-PRV-002`

## Ownership boundary

This packet owns the following implementation surface:

- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/schemas/provider-config.schema.json`
- `docs/examples/fixtures/provider-config.valid.json`
- `docs/examples/fixtures/provider-config.invalid.json`
- `docs/examples/project-scaffold/.audiagentic/providers.yaml.example`
- `src/audiagentic/execution/providers/health.py`
- `tests/integration/providers/test_selection.py`
- `tests/unit/contracts/test_schema_validation.py`
- `tests/integration/test_example_scaffold.py`

### It may read from
- frozen contracts in `docs/specifications/architecture/`
- approved fixtures under `docs/examples/fixtures/`
- outputs from dependency packets only

### It must not edit directly
- files owned by other groups unless a dependency explicitly requires it
- tracked release docs outside the owned writer module
- contract schemas unless this packet is in the contracts ownership chain

## Public contracts used

- schemas and shapes from `docs/specifications/architecture/03_Common_Contracts.md`
- phase gates from `docs/implementation/02_Phase_Gates_and_Exit_Criteria.md`
- ownership rules from `docs/implementation/05_Module_Ownership_and_Parallelization_Map.md`

## Detailed build steps

1. Extend the ProviderConfig contract to include `access-mode`.
2. Update the provider-config schema to require and validate `access-mode`.
3. Update the provider-config fixtures and scaffold example.
4. Implement access-mode-aware config validation in provider health checks.
5. Update selection tests to cover access-mode validation.
6. Run schema validation and provider selection tests.

## Access-mode rules

Allowed `access-mode` values for MVP:
- `env` — requires `auth-ref: env:NAME`
- `cli` — expects the provider CLI to supply credentials at runtime
- `none` — no authentication required (typical for local endpoints)

## Tests to add or update

- provider selection tests for `access-mode` validation
- schema validation fixtures to include `access-mode`
- scaffold validation to include `access-mode`

## Acceptance criteria

- ProviderConfig contract includes `access-mode` with documented rules.
- provider-config schema enforces `access-mode` and requires `auth-ref` for `env`.
- health checks mark providers unconfigured when access-mode requirements are not met.
- updated fixtures and scaffold validate cleanly.

## Recovery procedure

If this packet fails mid-implementation:
- revert edits to `docs/specifications/architecture/03_Common_Contracts.md`
- revert edits to `docs/schemas/provider-config.schema.json`
- revert updated fixtures and scaffold example
- rerun `python -m pytest tests/unit/contracts/test_schema_validation.py tests/integration/providers/test_selection.py tests/integration/test_example_scaffold.py`

## Parallelization note

This packet may run in parallel only after all dependencies are merged and only with packets whose ownership boundary does not overlap this packet.

## Out of scope

- adding new provider adapters
- changing provider selection order or failover policy
- adding non-MVP secret reference types
