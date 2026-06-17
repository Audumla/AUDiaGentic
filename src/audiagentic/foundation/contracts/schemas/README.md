# foundation/contracts/schemas/

## Purpose
JSON Schema definitions for all AUDiaGentic configuration and data contracts. These are the single source of truth for schema validation across the entire system.

## Ownership
- All `.json` schema files used by the system
- Schema discovery and registry support

## Must NOT Own
- Python validation logic (→ `foundation/contracts/schema_registry.py`)
- Configuration loading (→ `foundation/config/`)
- Runtime data (→ `.audiagentic/runtime/`)

## Schema inventory

### Config schemas

| Schema file | Validates |
|-------------|-----------|
| `provider-config.schema.json` | `.audiagentic/providers.yaml` |
| `project-config.schema.json` | `.audiagentic/project.yaml` |
| `prompt-syntax.schema.json` | `.audiagentic/prompt-syntax.yaml` |
| `component-config.schema.json` | Component configuration |

### Provider schemas

| Schema file | Validates |
|-------------|-----------|
| `provider-descriptor.schema.json` | Provider descriptor |
| `provider-health.schema.json` | Provider health status |
| `provider-model-catalog.schema.json` | Provider model catalog |
| `provider-session-input.schema.json` | Provider session input |
| `provider-session-manifest.schema.json` | Provider session manifest |
| `provider-stream-event.schema.json` | Provider stream event |
| `provider-stream-manifest.schema.json` | Provider stream manifest |
| `provider-completion.schema.json` | Provider completion result |

### Job / Workflow schemas

| Schema file | Validates |
|-------------|-----------|
| `job-record.schema.json` | Job record |
| `stage-result.schema.json` | Stage result |
| `lifecycle-plan.schema.json` | Lifecycle plan |
| `lifecycle-result.schema.json` | Lifecycle result |

### Prompt / Execution schemas

| Schema file | Validates |
|-------------|-----------|
| `prompt-launch-request.schema.json` | Prompt launch request |
| `approval-request.schema.json` | Approval request |

### Event schemas

| Schema file | Validates |
|-------------|-----------|
| `event-envelope.schema.json` | Event envelope |
| `change-event.schema.json` | Change event |

### Review schemas

| Schema file | Validates |
|-------------|-----------|
| `review-bundle.schema.json` | Review bundle |
| `review-report.schema.json` | Review report |

### Validation / Error schemas

| Schema file | Validates |
|-------------|-----------|
| `validation-report.schema.json` | Validation report |
| `error-envelope.schema.json` | Error envelope |

## Access pattern
Schemas are loaded via `foundation/contracts/schema_registry.py`:

```python
from audiagentic.foundation.contracts.schema_registry import read_schema
schema = read_schema("provider-config")
```

## Adding a new schema

1. Add `<name>.schema.json` to this directory
2. Register it in `schema_registry.py` if it needs a named lookup
3. Add a validation test under `tests/unit/contracts/`
