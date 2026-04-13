# foundation/

Shared primitives, contracts, and configuration infrastructure for the AUDiaGentic system.

## Purpose

The foundation layer provides:
- Machine-readable schemas and contracts (`contracts/`)
- Configuration loading and validation (`config/`)
- Canonical error types and envelopes
- ID generation and validation rules

All other layers in AUDiaGentic depend on foundation; foundation depends on nothing except stdlib and third-party libraries.

## Owns

- `contracts/`: Schemas, error types, canonical IDs, glossary
- `config/`: Provider registry, catalog, and configuration loaders

## Must not own

- Job orchestration
- Provider-specific behavior
- Runtime state management
- Release logic
- Channel behavior
- Protocol implementations

## Allowed dependencies

**Exports to**: All other layers (execution, runtime, interoperability, channels, planning, knowledge, release)

**Imports from**: None (except stdlib/third-party)

## Examples

```python
# Correct: Load a schema from foundation
from audiagentic.foundation.contracts.schema_registry import read_schema

# Correct: Get the canonical error type
from audiagentic.foundation.contracts.errors import AudiaGenticError

# Correct: Load provider configuration
from audiagentic.foundation.config.provider_registry import load_provider_registry
```

## Anti-examples

```python
# WRONG: foundation should not import from execution
from audiagentic.foundation.execution.jobs import ...  # BAD

# WRONG: foundation should not manage provider adapters
# That belongs in interoperability/providers/
```

## Migration notes

- Moved from `contracts/` and `config/` roots (2026-04-12)
- All imports updated to `audiagentic.foundation.contracts.*` and `audiagentic.foundation.config.*`
- Relative path updates in `planning/app/config.py` to locate schemas at foundation/contracts/schemas/
