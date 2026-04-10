# PKT-PRV-043 — GitHub Copilot auto-install integration

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Wire Copilot availability checks into the shared bootstrap harness so missing Copilot support can be installed or initialized from config when allowed.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-007 is verified
- PKT-PRV-018 is ready or verified

## Implementation steps
1. document Copilot install or login guidance in the provider doc
2. add Copilot bootstrap guidance to provider config
3. hook the Copilot availability probe into the shared install harness
4. add Copilot auto-install and manual fallback tests

## Acceptance criteria
- Copilot missing-state handling can bootstrap when policy allows it
- Copilot remains install-policy driven rather than hard-coded
- the provider can still be skipped cleanly when auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/05_Copilot.md
- .github/copilot-instructions.md
- Copilot install smoke tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
