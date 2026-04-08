---
id: spec-0004
label: Phase 0 Contracts and Scaffolding
state: draft
summary: Machine-verifiable baseline for all later phases - contracts, schemas, fixtures,
  validators
request_refs:
- request-0002
task_refs: []
---

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

1. [PKT-FND-001](task-0032) — Canonical IDs and Naming Normalization
2. [PKT-FND-002](task-0033) — Schema Package and Fixtures
3. [PKT-FND-003](task-0034) — Example Project Scaffold
4. [PKT-FND-004](task-0035) — Lifecycle CLI Stub
5. [PKT-FND-005](task-0036) — Packet/Test Harness Scaffolding
6. [PKT-FND-006](task-0037) — Naming Validator Script
7. [PKT-FND-007](task-0038) — Schema Validator Script
8. [PKT-FND-008](task-0039) — Checkpoint Writer
9. [PKT-FND-009](task-0040) — Fixture Generator
10. [PKT-FND-010](task-0041) — Integration Tests
11. [PKT-FND-011](task-0042) — Documentation
12. [PKT-FND-012](task-0043) — Migration Runbook
13. [PKT-FND-013](task-0044) — Exit Gate Validation

## Exit gate

- all schema files are non-placeholder
- validator passes all valid fixtures
- validator fails all invalid fixtures
- naming validator returns success on the docs/examples tree
- lifecycle CLI stub writes deterministic checkpoint artifacts under `.audiagentic/runtime/lifecycle/`

# Requirements

1. Schema files must be machine-verifiable
2. Validators must distinguish valid from invalid fixtures
3. All outputs must be deterministic

# Constraints

- No business logic before Phase 0 complete
- All contracts must be frozen before Phase 1

# Acceptance Criteria

1. All schema files populated and versioned
2. Validators pass all valid fixtures
3. Validators fail all invalid fixtures
4. Lifecycle CLI stub writes deterministic checkpoints
