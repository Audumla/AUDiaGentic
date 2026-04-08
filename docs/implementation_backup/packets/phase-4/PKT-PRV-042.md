# PKT-PRV-042 — Gemini auto-install integration

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Wire Gemini availability checks into the shared bootstrap harness so missing Gemini support can be installed or initialized from config when allowed.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-006 is verified
- PKT-PRV-017 is in progress or ready

## Implementation steps
1. document Gemini installation or bootstrap guidance in the provider doc
2. add Gemini bootstrap or login initialization guidance to provider config
3. hook the Gemini availability probe into the shared install harness
4. add Gemini auto-install and manual fallback tests

## Acceptance criteria
- Gemini missing-state handling can bootstrap when policy allows it
- Gemini remains install-policy driven rather than hard-coded
- the provider can still be skipped cleanly when auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/04_Gemini.md
- GEMINI.md / command-template guidance
- Gemini install smoke tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
