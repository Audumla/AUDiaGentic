# PKT-PRV-039 — Shared provider availability and auto-install contract + bootstrap harness

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Define the shared availability contract and a reusable bootstrap harness that can probe a provider, decide whether installation is allowed, and re-check availability after bootstrapping.

## Prerequisites
- PKT-PRV-012 is verified
- PKT-PRV-013 is verified
- PKT-PRV-031 is drafted

## Implementation steps
1. define the shared install policy and availability response shape
2. add the generic bootstrap harness or installer wrapper contract
3. connect the harness to the existing provider status checks
4. add tests for allowed, skipped, prompted, and manually blocked install cases

## Acceptance criteria
- the system can tell whether a provider is available before launch
- the shared harness can decide what to do when a provider is missing
- the install policy is opt-in and project-local
- the same harness can be reused by every provider packet

## Likely files or surfaces
- provider config schema and examples
- project config schema and examples
- availability probe / install harness
- install policy documentation

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
