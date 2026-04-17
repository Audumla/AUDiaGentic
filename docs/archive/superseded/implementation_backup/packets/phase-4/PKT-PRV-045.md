# PKT-PRV-045 — Cline auto-install integration

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Wire Cline availability checks into the shared bootstrap harness so missing Cline support can be installed or initialized from config when allowed.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-009 is verified
- PKT-PRV-020 is ready or verified

## Implementation steps
1. document Cline install or workspace bootstrap guidance in the provider doc
2. add Cline bootstrap guidance to provider config
3. hook the Cline availability probe into the shared install harness
4. add Cline auto-install and manual fallback tests

## Acceptance criteria
- Cline missing-state handling can bootstrap when policy allows it
- Cline remains install-policy driven rather than hard-coded
- the provider can still be skipped cleanly when auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/07_Cline.md
- .clinerules / workflow guidance
- Cline install smoke tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
