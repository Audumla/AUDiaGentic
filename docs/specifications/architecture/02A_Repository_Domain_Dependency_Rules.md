# Repository-Domain Dependency Rules (v3)

> **Updated for v3 structural refactor.** This document replaces the pre-refactor
> `Phase 0.3` addendum. Domain names now reflect the live `src/audiagentic/` tree.

## Purpose

Defines the canonical package-level repository-domain dependency rules for the v3 structure.
This is the single source of truth for which domain may import from which.

## Active domains

Under `src/audiagentic/`:

- `foundation` — shared contracts and configuration (base layer)
- `planning` — planning workflows and task management
- `execution` — job orchestration
- `interoperability` — external provider integrations and protocols
- `runtime` — lifecycle management and durable state persistence
- `release` — release governance and audit
- `channels` — operator-facing surfaces
- `knowledge` — optional capability domain (scaffold only)

## Allowed repository-domain dependencies

- `foundation` has no repository-domain dependencies (it is the base layer)
- `planning` may depend on `foundation`
- `execution` may depend on `foundation`, `runtime`, `interoperability`
- `interoperability` may depend on `foundation`, `execution` (see seam note below)
- `runtime` may depend on `foundation`
- `release` may depend on `foundation`, `runtime`
- `channels` may depend on `foundation`, `runtime`, `execution`, `release`
- `knowledge` may depend on `foundation`

## Forbidden repository-domain dependencies

- `foundation → any domain`
- `runtime → channels`, `runtime → execution`, `runtime → release`
- `execution → channel formatting or rendering internals`
- `channels → execution internals beyond approved entrypoints`
- `release → channels`, `release → execution`

## Approved cross-layer seam

`interoperability/providers/adapters/gemini.py` → `execution.jobs.prompt_launch` and
`execution.jobs.prompt_parser`.

This is a one-way, documented dependency. The direction (interoperability → execution) is
approved because the gemini adapter needs to launch sub-jobs. It must not be expanded without
a boundary review.

## Enforcement

Run after any code motion:

```bash
python tools/checks/check_cross_domain_imports.py
```

This tool enforces the allowed/forbidden rules above by scanning all Python source under
`src/audiagentic/` and reporting violations.
