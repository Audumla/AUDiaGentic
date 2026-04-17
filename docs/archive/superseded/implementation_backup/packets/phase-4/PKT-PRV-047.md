# PKT-PRV-047 — Qwen auto-install integration

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Wire Qwen availability checks into the shared bootstrap harness so missing Qwen support can be installed or initialized from config when allowed.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-030 is verified
- PKT-PRV-021 is ready or verified

## Implementation steps
1. document Qwen install or bootstrap guidance in the provider doc
2. add Qwen bootstrap guidance to provider config
3. hook the Qwen availability probe into the shared install harness
4. add Qwen auto-install and manual fallback tests

## Acceptance criteria
- Qwen missing-state handling can bootstrap when policy allows it
- Qwen remains install-policy driven rather than hard-coded
- the provider can still be skipped cleanly when auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/08_Qwen.md
- .qwen/settings.json guidance
- Qwen install smoke tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
