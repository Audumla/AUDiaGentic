# foundation/contracts/

Machine-readable contracts, schemas, and error definitions.

## Purpose

Defines the canonical data formats, error envelopes, and ID generation rules for the system.

## Owns

- Schemas (JSON Schema files in `schemas/` subdirectory)
- Error types and error envelope construction (`errors.py`)
- ID validation and canonical ID sets (`canonical_ids.py`)
- Glossary of canonical terms (`glossary.py`)
- Schema registry and discovery (`schema_registry.py`)

## Key modules

- **errors.py**: `AudiaGenticError`, `to_error_envelope`
- **schema_registry.py**: `read_schema()`, `iter_schema_paths()`, schema file discovery
- **canonical_ids.py**: `validate_ids()`, provider and packet ID validation
- **glossary.py**: Canonical term definitions
- **schemas/**: Flat JSON Schema files (job-record, review-report, etc.)
- **schemas/planning/**: Planning-specific schemas (request, task, plan, etc.)

## Must not own

- Validation logic that calls external services
- Provider-specific schemas
- Runtime state
- Any layer that depends on execution or runtime behavior
