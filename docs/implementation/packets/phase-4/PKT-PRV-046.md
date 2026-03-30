# PKT-PRV-046 — local-openai availability and bridge bootstrap

**Phase:** Phase 4.7
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective
Define how the backend-only local-openai surface reports availability and bootstraps the repo-owned bridge/configuration when missing.

## Prerequisites
- PKT-PRV-039 is drafted
- PKT-PRV-003 is verified
- PKT-PRV-021 is ready or verified

## Implementation steps
1. document the bridge bootstrap path for local-openai in the provider doc
2. define the local-openai availability probe for bridge-backed setups
3. hook the bridge bootstrap into the shared install harness
4. add local-openai bridge availability and skip-path tests

## Acceptance criteria
- local-openai availability can be reported even when the backend is external
- the bridge can be installed or configured when policy allows it
- the provider can still be skipped cleanly when bridge auto-install is disabled

## Likely files or surfaces
- docs/specifications/architecture/providers/01_Local_OpenAI_Compatible.md
- bridge wrapper guidance
- local-openai availability tests

## Rollback guidance
- revert the provider-specific availability/bootstrap changes only
- leave the shared launch grammar untouched
