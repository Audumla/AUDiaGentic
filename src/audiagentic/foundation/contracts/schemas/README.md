# foundation/contracts/schemas/

## Purpose
JSON Schema definitions for all AUDiaGentic configuration and data contracts. These are the single source of truth for schema validation across the entire system.

## Ownership
- All `.json` schema files used by the system
- Planning-specific schemas (`planning/` subdirectory)
- Schema discovery and registry support

## Must NOT Own
- Python validation logic (→ `foundation/contracts/schema_registry.py`)
- Configuration loading (→ `foundation/config/`)
- Runtime data (→ `.audiagentic/runtime/`)

## Schema inventory

| Schema file | Validates |
|-------------|-----------|
| `provider-config.schema.json` | `.audiagentic/providers.yaml` |
| `project-config.schema.json` | `.audiagentic/project.yaml` |
| `prompt-syntax.schema.json` | `.audiagentic/prompt-syntax.yaml` |
| `installed-manifest.schema.json` | `.audiagentic/installed.json` |
| `planning/*.json` | Planning item types (request, spec, task, etc.) |

## Access pattern
Schemas are loaded via `foundation/contracts/schema_registry.py`:

```python
from audiagentic.foundation.contracts.schema_registry import get_schema
schema = get_schema("provider-config")
```

## Adding a new schema
1. Add `<name>.schema.json` to this directory (or `planning/` if planning-specific)
2. Register it in `schema_registry.py` if it needs a named lookup
3. Add a validation test under `tests/unit/contracts/`
