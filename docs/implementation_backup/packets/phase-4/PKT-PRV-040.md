# PKT-PRV-040 — Codex auto-install integration

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Wire Codex availability checks into the shared bootstrap harness so missing Codex support can be installed or initialized from config when allowed.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-005 is verified
- PKT-PRV-015 is ready or verified

## Implementation steps
1. document Codex install or bootstrap guidance in the provider doc
2. add the Codex bootstrap command or wrapper path to provider config
3. hook the Codex availability probe into the shared install harness
4. add Codex auto-install and manual fallback tests

## Acceptance criteria
- Codex missing-state handling can bootstrap when policy allows it
- Codex remains install-policy driven rather than hard-coded
- the provider can still be skipped cleanly when auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/03_Codex.md
- AGENTS.md or wrapper guidance
- Codex install smoke tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
