---
id: spec-0009
label: Phase 1 Lifecycle and Project Enablement
state: draft
summary: Safe installation, update, cutover, uninstall, and project enablement
request_refs:
- request-0002
task_refs: []
---

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
- provider install/bootstrap policy field preservation for later provider auto-install features
- installable managed baseline sync so the repository's tracked prompt/provider assets can be applied to other projects

## Out of scope

- release ledger logic
- job execution
- provider execution
- Discord delivery

## Implementation order

1. [PKT-LFC-001](task-0045) — installed-state detector
2. [PKT-LFC-002](task-0046) — lifecycle manifest and checkpoint writer
3. [PKT-LFC-003](task-0047) — fresh install apply/validate
4. [PKT-LFC-004](task-0048) — update dispatch and version module selection
5. [PKT-LFC-005](task-0049) — legacy cutover
6. [PKT-LFC-006](task-0050) — uninstall current AUDiaGentic
7. [PKT-LFC-007](task-0051) — document migration outcomes and reports
8. [PKT-LFC-010](task-0052) — preserve provider auto-install policy fields across lifecycle commands
9. [PKT-LFC-011](task-0053) — installable baseline inventory and sync-mode classification
10. [PKT-LFC-012](task-0054) — shared baseline sync engine for lifecycle and bootstrap
11. [PKT-LFC-013](task-0055) — converge fresh-install and release-bootstrap on baseline sync

## Exit gate

- all lifecycle commands support `plan`, `apply`, and `validate`
- destructive test cases pass in sandbox repositories
- mixed-or-invalid state is detected and returns blocking error with remediation guidance
- managed workflow rename path emits a warning and creates summary output

# Requirements

1. Lifecycle must be safe and reversible
2. All commands must support plan/apply/validate
3. State detection must be accurate

# Constraints

- No release ledger logic
- No job execution
- No provider execution
- No Discord delivery

# Acceptance Criteria

1. All lifecycle commands functional
2. Destructive tests pass in sandbox
3. State detection accurate
4. Migration reports generated
