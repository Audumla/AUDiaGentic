---
id: EDJ17
order: 15
plan: event-driven-jobs
state: completed
validate-first: true
priority: P1
work: S
created-by: codex
---

# Codify contract schema ownership and mirror drift guards

## Description

Before adding event-trigger and prompt-launch schema changes across component and foundation contract locations, define one schema ownership rule and a test that prevents component/foundation copies from drifting.

## Steps

1. Decide and document the authoritative source for contract schemas that exist in both `components/<component>/contracts` and `foundation/contracts/schemas`.
2. Add or update architecture/component standards with the synchronization rule: schema updates must change both copies or generate one from the other.
3. Add a focused test that compares mirrored schema files for known mirrored contracts and includes `event-trigger` once EDJ01 adds it.
4. Update EDJ01/EDJ03/EDJ11 validation notes to require the drift guard before relying on changed schemas.

## Files

docs/standards/ARCHITECTURE_STANDARDS.md
docs/standards/CREATING_A_COMPONENT.md
src/audiagentic/foundation/contracts/schemas/*.schema.json
src/audiagentic/components/agent_jobs/contracts/*.schema.json
tests/unit/foundation/test_schema_registry.py or equivalent

## Validation

Test fails when a mirrored component contract differs from the canonical foundation schema. EDJ01 event-trigger schema is present in the canonical registry before loader validation uses it. Existing mirrored schemas still pass.

## Effort & Risk

Simple. Main risk is enshrining duplication; document current rule now, then leave future schema generation/consolidation as separate work if desired.

## Standards



## Notes



## Ledger Events


