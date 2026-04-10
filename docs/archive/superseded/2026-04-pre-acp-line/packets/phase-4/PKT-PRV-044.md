# PKT-PRV-044 — Continue auto-install integration

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Wire Continue availability checks into the shared bootstrap harness so missing Continue support can be installed or initialized from config when allowed.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-008 is verified
- PKT-PRV-019 is ready or verified

## Implementation steps
1. document Continue install or bootstrap guidance in the provider doc
2. add Continue bootstrap guidance to provider config
3. hook the Continue availability probe into the shared install harness
4. add Continue auto-install and manual fallback tests

## Acceptance criteria
- Continue missing-state handling can bootstrap when policy allows it
- Continue remains install-policy driven rather than hard-coded
- the provider can still be skipped cleanly when auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/06_Continue.md
- config.yaml guidance
- Continue install smoke tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
