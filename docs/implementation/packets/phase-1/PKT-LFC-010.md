# PKT-LFC-010 — Provider auto-install policy persistence and lifecycle roundtrip

**Phase:** Phase 1.3
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective

Preserve provider auto-install and bootstrap policy fields across lifecycle commands so
Phase 4.7 install behavior can be configured safely without being lost during install,
update, cutover, uninstall, or migration reporting.

## Prerequisites

- PKT-FND-008 is verified
- PKT-LFC-008 is verified
- PKT-PRV-039 is drafted

## Implementation steps

1. identify the config fields that must round-trip through lifecycle operations
2. update lifecycle validation or persistence helpers so the fields are preserved verbatim
3. ensure migration reports summarize the new fields without stripping them
4. add unit and integration tests for install/update/cutover/uninstall round-trip behavior

## Acceptance criteria

- lifecycle commands preserve provider install-policy fields unchanged
- invalid policy fields are rejected, but valid fields are not dropped
- installed-state and migration outputs stay stable when the fields are present
- the packet remains isolated from the provider execution and prompt-trigger layers

## Likely files or surfaces

- `src/audiagentic/runtime/lifecycle/*`
- `src/audiagentic/contracts/*`
- `docs/examples/fixtures/*.yaml`
- `docs/examples/fixtures/*.json`
- lifecycle unit and integration tests

## Rollback guidance

- revert the lifecycle persistence changes only
- keep the provider install-policy schema draft intact
