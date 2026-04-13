# foundation/config/

Configuration loading and validation for provider setup.

## Purpose

Provides loaders for provider configuration, registry, and model catalog.

## Owns

- Provider registry loading and validation
- Provider configuration parsing
- Model catalog reading/writing
- Configuration validation

## Key modules

- **provider_registry.py**: `load_provider_registry()`
- **provider_config.py**: `load_provider_config()`, `validate_provider_config()`
- **provider_catalog.py**: `read_model_catalog()`, `write_model_catalog()`, catalog validation

## Must not own

- Provider-specific execution logic
- Runtime state
- Release logic
