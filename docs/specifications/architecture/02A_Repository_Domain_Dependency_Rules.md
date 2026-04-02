# Repository-Domain Dependency Rules for Phase 0.3

## Purpose

This addendum defines the **canonical package-level repository-domain dependency rules** for the Phase 0.3 repository refactor.

It exists so `PKT-FND-011` and `PKT-FND-012` have one stable source for package-move guardrails even while `02_Core_Boundaries_and_Dependency_Rules.md` still carries the older subsystem-oriented model.

## Allowed repository-domain dependencies

- `contracts` may be imported by every domain
- `core` may be imported by every domain
- `config` may be imported by `execution`, `runtime`, `channels`, `streaming`, and `observability`
- `scoping` may depend on `contracts`, `core`, and `config`
- `execution` may depend on `contracts`, `core`, `config`, and selected `runtime` ports
- `runtime` may depend on `contracts`, `core`, and `config`
- `channels` may depend on `contracts`, `core`, `config`, and selected presentation-facing runtime records
- `streaming` may depend on `execution`, `runtime`, `channels`, `contracts`, and `core`
- `observability` may depend on `runtime`, `contracts`, `core`, and `config`

## Forbidden repository-domain dependencies

- `scoping -> channels`
- `scoping -> observability`
- `execution ->` channel formatting or rendering internals
- `observability ->` live interaction control
- `channels ->` execution internals
- `runtime -> channels`

## Extension-root note

`nodes`, `discovery`, `federation`, and `connectors` remain reserved extension roots under `src/audiagentic/` during this tranche. They are not folded into the baseline repository-domain taxonomy for Phase 0.3 code motion, even if they later align conceptually with `runtime`, `channels`, `streaming`, or `observability`.

## Enforcement note

During Phase 0.3, `tools/check_cross_domain_imports.py` should enforce these rules for any moved or newly introduced package edges.
