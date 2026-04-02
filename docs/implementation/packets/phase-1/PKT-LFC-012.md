# PKT-LFC-012 — Shared baseline sync engine for lifecycle and bootstrap

**Phase:** Phase 1.4  
**Status:** VERIFIED  
**Owner:** Lifecycle  
**Scope:** workspace

## Goal

Implement a shared baseline sync engine that applies the managed install baseline to a target project according to sync-mode rules instead of using multiple hard-coded copy lists.

## Dependencies

- `PKT-LFC-011` VERIFIED
- `PKT-FND-013` VERIFIED (checkpoint: repository domain refactor completes before baseline-sync engine implementation resumes)

## Expected implementation surface

- `src/audiagentic/runtime/lifecycle/baseline_sync.py`
- `tools/seed_example_project.py`
- supporting tests for inventory and copy/preserve behavior

## Must support

- required-managed assets
- create-if-missing assets
- generated-managed outputs reported but not copied
- runtime-only exclusions
- machine-readable sync report

## Acceptance criteria

- one shared sync seam exists for lifecycle/bootstrap
- sync results distinguish created, refreshed, preserved, skipped, and excluded paths
- runtime-only paths cannot be copied as baseline assets

## Verification note

Verified on 2026-04-02 after `runtime/lifecycle/baseline_sync.py` was implemented, baseline seeding and release bootstrap were rewired onto the inventory-driven sync seam, and the focused lifecycle/bootstrap validation suite passed.
