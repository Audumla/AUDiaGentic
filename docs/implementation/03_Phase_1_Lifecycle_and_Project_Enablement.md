# Phase 1 — Lifecycle and Project Enablement

## Purpose

Implement safe installation, update, cutover, uninstall, and project enablement before any higher-level behavior touches real projects.

## Scope

- installed-state detection
- fresh install
- update dispatch
- legacy cutover
- uninstall current AUDiaGentic
- document migration report generation
- managed workflow replacement warnings

## Out of scope

- release ledger logic
- job execution
- provider execution
- Discord delivery

## Implementation order

1. PKT-LFC-001 — installed-state detector
2. PKT-LFC-002 — lifecycle manifest and checkpoint writer
3. PKT-LFC-003 — fresh install apply/validate
4. PKT-LFC-004 — update dispatch and version module selection
5. PKT-LFC-005 — legacy cutover
6. PKT-LFC-006 — uninstall current AUDiaGentic
7. PKT-LFC-007 — document migration outcomes and reports

## Exit gate

- all lifecycle commands support `plan`, `apply`, and `validate`
- destructive test cases pass in sandbox repositories
- mixed-or-invalid state is detected and returns blocking error with remediation guidance
- managed workflow rename path emits a warning and creates summary output
