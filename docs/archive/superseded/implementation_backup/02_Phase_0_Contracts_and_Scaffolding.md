# Phase 0 — Contracts and Scaffolding

## Purpose

Create the machine-verifiable baseline that every later phase depends on.
No business logic starts before this phase is complete.

## Scope

- canonical ids and naming normalization
- schema package and fixtures
- example project scaffold
- lifecycle CLI stub
- packet/test harness scaffolding

## Out of scope

- destructive lifecycle actions
- release ledger writes
- provider API calls
- Discord integration

## Required outputs

1. `src/audiagentic/contracts/schemas/*.schema.json` populated and versioned
2. `docs/examples/fixtures/*` valid and invalid fixtures
3. naming validator script
4. schema validator script
5. lifecycle CLI stub and checkpoint writer
6. example `.audiagentic/` project scaffold

## Implementation order

1. PKT-FND-001
2. PKT-FND-002
3. PKT-FND-003
4. PKT-FND-004
5. PKT-FND-005

## Exit gate

- all schema files are non-placeholder
- validator passes all valid fixtures
- validator fails all invalid fixtures
- naming validator returns success on the docs/examples tree
- lifecycle CLI stub writes deterministic checkpoint artifacts under `.audiagentic/runtime/lifecycle/`
