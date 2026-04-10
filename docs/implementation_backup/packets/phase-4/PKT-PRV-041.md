# PKT-PRV-041 — Claude auto-install integration

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Wire Claude availability checks into the shared bootstrap harness so missing Claude support can be installed or initialized from config when allowed.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-004 is verified
- PKT-PRV-016 is ready or verified

## Implementation steps
1. document Claude installation or bootstrap guidance in the provider doc
2. add Claude bootstrap or login initialization guidance to provider config
3. hook the Claude availability probe into the shared install harness
4. add Claude auto-install and manual fallback tests

## Acceptance criteria
- Claude missing-state handling can bootstrap when policy allows it
- Claude remains install-policy driven rather than hard-coded
- the provider can still be skipped cleanly when auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/02_Claude.md
- CLAUDE.md / .claude/rules guidance
- Claude install smoke tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
