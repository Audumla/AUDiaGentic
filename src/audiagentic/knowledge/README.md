# knowledge/

Project knowledge storage, indexing, and retrieval (optional capability).

## Purpose

Provides pluggable knowledge management for projects:
- Knowledge corpus storage and indexing
- Retrieval and search
- Backend-pluggable implementations
- Integration with planning and execution

## Status

**Scaffold only. No executable code exists in this directory.**

This domain is reserved to prevent other modules from absorbing knowledge-management ownership by default. The `__init__.py` contains only a module docstring. All real implementation is deferred to a post-refactor work item.

When implementation begins, the entry point will be `knowledge/__init__.py` re-exported as the public API with submodules under the structure listed below.

## Future structure (planned)

```
knowledge/
  catalog/       - Knowledge source catalog
  ingest/        - Ingestion and processing
  retrieval/     - Search and retrieval engines
  backends/      - Backend implementations (file, vector DB, etc.)
  policies/      - Access and retention policies
```

## Must not own

- Planning workflows (those stay in planning/)
- Provider-specific execution
- Runtime lifecycle
- Release management

## Must support

- Optional enablement per project
- Multiple backend implementations
- Project-local content without shared system code ownership

## Optional-install model

Knowledge is shipped in the shared AUDiaGentic installation but can be:
- Enabled or disabled per consuming project
- Backed by different implementations per project
- Fully deferred if not needed

## Migration notes

- Introduced as scaffolding in Slice I (2026-04-12)
