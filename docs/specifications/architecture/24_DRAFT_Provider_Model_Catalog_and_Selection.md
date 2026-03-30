# DRAFT — Provider Model Catalog and Selection

## Purpose

Providers regularly update their available models. AUDiaGentic needs a stable mechanism to:
- refresh an up-to-date catalog of available models
- allow easy switching between models per provider
- keep job execution deterministic when a model choice changes

This draft defines the contract for provider model catalogs and selection rules to be implemented in Phase 4.1.

## Scope (Phase 4.1)

- provider model catalog contract
- CLI refresh command
- model alias and selection rules
- runtime storage for model catalogs

## Out of scope

- automatic provider failover
- cross-provider model normalization
- dynamic model scoring

## Provider Model Catalog (DRAFT contract)

```json
{
  "contract-version": "v1",
  "provider-id": "codex",
  "fetched-at": "2026-03-30T00:00:00Z",
  "source": "cli",
  "models": [
    {
      "model-id": "codex-pro",
      "display-name": "Codex Pro",
      "status": "active",
      "supports-structured-output": true,
      "context-window": 200000
    }
  ]
}
```

Rules:
- catalog is stored under `.audiagentic/runtime/providers/<provider-id>/model-catalog.json`
- `source` enum: `cli`, `api`, `static`
- model `status` enum: `active`, `deprecated`, `experimental`
- catalog refresh must be explicit and deterministic

## ProviderConfig extensions (DRAFT)

```yaml
providers:
  codex:
    enabled: true
    install-mode: external-configured
    access-mode: cli
    default-model: codex-pro
    model-aliases:
      fast: codex-mini
      deep: codex-pro
    catalog-refresh:
      source: cli
      max-age-hours: 168
```

Rules:
- `default-model` remains the fallback when no job model is specified.
- `model-aliases` lets teams switch model targets without changing job requests.
- `catalog-refresh.max-age-hours` controls stale catalog warnings only (no automatic refresh in MVP).

## Model selection rules (DRAFT)

Order of resolution:
1. explicit `model-id` on job request
2. `model-alias` on job request (resolved through `model-aliases`)
3. provider `default-model`
4. fail with validation error if none resolve

Selection validation:
- if catalog exists, resolved model must exist in catalog
- if catalog is missing or stale, emit a warning but allow execution in MVP

## CLI refresh (DRAFT)

Command shape:
- `audiagentic-providers refresh-model-catalog --provider-id <id> --source cli|api|static --json`

Rules:
- writes catalog atomically
- respects `access-mode`
- returns ErrorEnvelope on failure

## Phase 4.1 exit gate (draft)

- provider model catalog schema and fixtures exist
- refresh command works for at least one CLI-backed provider
- model selection logic resolves aliases and defaults deterministically
- provider documentation updated with model catalog guidance
