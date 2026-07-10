---
id: EDJ19
order: 5
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: simple
created-by: claude
---

# Schema ownership and mirror-drift guard for duplicated contracts

## Description

From RV231: contracts are duplicated between `foundation/contracts/schemas/` (the copy schema_registry actually loads and validates against) and `components/<component>/contracts/` (the component-owned copy), e.g. job-record.schema.json exists in both with no rule about which is authoritative and no drift detection. EDJ01 adds event-trigger.schema.json and EDJ03 extends job-record.schema.json — both expand the duplicated surface. Codify ownership and add a drift test BEFORE those items land.

## Steps

1. Add a 'Contract schema ownership' rule to ARCHITECTURE_STANDARDS.md: the component copy under `components/<component>/contracts/` is authoritative (component owns its contract); the `foundation/contracts/schemas/` copy is the registry mirror used for canonical validation; every mirrored schema must be byte-identical.
2. Add a drift test (tests/unit/foundation/) that walks foundation/contracts/schemas/, finds the matching component copy by filename, and asserts byte equality — failing with a message naming the authoritative copy to re-sync from. Schemas without a component copy are exempt (foundation-native contracts).
3. Decide + document whether event-trigger.schema.json is mirrored into foundation/contracts/schemas/ at all: it is only consumed by agent-jobs, so the default is component-only (NOT mirrored, not in schema_registry) unless canonical cross-component validation is needed. Record the decision in the standard.
4. Update the schemas README with the ownership rule.

## Files

docs/standards/ARCHITECTURE_STANDARDS.md
src/audiagentic/foundation/contracts/schemas/README.md
tests/unit/foundation/test_schema_mirror_drift.py

## Validation

Drift test passes on current tree (or surfaces and fixes existing drift); intentionally desyncing a mirrored schema in a temp fixture fails the test; standard section reviewed; EDJ01/EDJ03/EDJ11 reference the decided ownership rule.

## Effort & Risk

Simple. One standard paragraph + one test. Risk is only in step 3's decision; default (component-only for event-trigger) avoids growing the mirror.

## Standards

arch-standards — config-over-code, single source of truth for contracts.

## Notes

From review RV231 (codex). Gates EDJ01 and EDJ03: neither should add/extend schemas until ownership is codified. EDJ01's files list should drop foundation schema_registry/canonical_ids edits if step 3 decides component-only.

## Ledger Events


