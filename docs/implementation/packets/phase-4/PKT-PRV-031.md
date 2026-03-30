# PKT-PRV-031 — Shared provider prompt-trigger launch contract + bridge harness

**Phase:** Phase 4.6
**Status:** DEFERRED_DRAFT
**Owner:** shared

## Objective
Implement the shared bridge that lets a tagged prompt become a normalized launch request, then invoke the existing prompt-launch pipeline.

## Prerequisites
- the Phase 3.2 launch contract is already verified
- the Phase 4.3 prompt-tag grammar is already verified
- the Phase 4.4 provider execution contract stays frozen

## Implementation steps
1. create the shared trigger bridge/wrapper entry point
2. normalize first-line tags and provider shorthands into the existing prompt-launch request shape
3. preserve provider, surface, and session provenance
4. add unit and integration tests for the shared bridge path

## Acceptance criteria
- a tagged prompt can invoke the shared launcher through the bridge
- the bridge preserves provenance and does not rewrite the shared grammar
- the bridge works for at least one provider-owned surface and one repo-owned wrapper surface

## Likely files or surfaces
- PromptLaunchRequest parser and launcher
- provider prompt-tag surface contract docs
- shared wrapper or bridge script

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
