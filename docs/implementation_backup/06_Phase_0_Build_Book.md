# Phase 0 — Contracts and scaffolding

This phase freezes the contracts and creates the deterministic scaffolding used by every later phase. No destructive project changes are allowed in this phase. The goal is to leave behind validated schemas, fixtures, validators, glossary/canonical-id enforcement, and a lifecycle CLI stub that can be executed safely in test repositories.

## Phase deliverables

See the packet files for exact build steps.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.

## v12 corrective additions

Phase 0 now also produces:
- shared error envelope and error-code registry
- CI/testing infrastructure guidance and validator expectations
- packet dependency graph validation
