# PKT-PRV-056 — Shared provider structured-completion contract and normalization harness

**Phase:** Phase 4.11
**Status:** READY_TO_START
**Owner:** Codex

## Objective

Implement the shared structured-completion contract and normalization harness so provider
results can be persisted as canonical AUDiaGentic final-result artifacts instead of relying on
synthetic fallback records whenever a provider does not return the exact shape by default.

## Scope

This packet owns:

- shared final-result envelope rules
- shared normalization helper(s)
- direct-versus-fallback result marking
- canonical persistence seam for normalized provider results
- shared tests and fixtures for the result envelope

## Dependencies

- `PKT-PRV-048`
- `PKT-PRV-051`
- `PKT-PRV-031`
- current review/job artifact persistence seams

## Acceptance criteria

- canonical final-result envelope is frozen in docs and shared code
- normalized results can distinguish direct provider output from fallback-derived output
- raw provider output remains available for diagnosis
- shared tests prove canonical result normalization independent of provider-specific wrappers

## Notes

- this packet does not pick one single provider completion mechanism
- this packet exists to keep result normalization shared and provider-neutral

## Integration Seam

This packet defines the shared harness but does not wire it into the main execution flow. Provider-specific integration packets (e.g., `PKT-PRV-057`, `PKT-PRV-069`) are responsible for utilizing this seam. The intended call flow is:

1. Provider adapter executes and receives raw stdout/stderr and returncode.
2. Adapter parses specific output or falls back (using `try_extract_json_from_stdout`).
3. Adapter creates a canonical completion via `normalize_provider_result()` or `build_synthetic_fallback()`.
4. Adapter persists the artifact to disk by calling `persist_completion()`.
5. The execution engine (e.g., `prompt_launch.py`) reads this completion artifact to update job state and review bundles.
