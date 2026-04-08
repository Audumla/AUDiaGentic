---
id: spec-0010
label: Phase 2 Release Audit Ledger and Release Please
state: draft
summary: Build release core independent of jobs
request_refs:
- request-0002
task_refs: []
---

# Phase 2 — Release, Audit, Ledger, and Release Please

## Purpose

Build the release core independent of jobs.

## Scope

- Fragment capture
- Sync with locking and idempotency
- Current release summary
- Audit/check-in summary generation
- Finalization with exactly-once historical append
- Release Please baseline workflow/config management

## Out of scope

- job execution
- provider execution
- Discord delivery

## Implementation order

1. [PKT-RLS-001](task-0056) — fragment capture
2. [PKT-RLS-002](task-0057) — sync with locking and idempotency
3. [PKT-RLS-003](task-0058) — current release summary
4. [PKT-RLS-004](task-0059) — audit/check-in summary generation
5. [PKT-RLS-005](task-0060) — finalization with exactly-once append
6. [PKT-RLS-006](task-0061) — Release Please baseline workflow
7. [PKT-RLS-007](task-0062) — Release Please config management
8. [PKT-RLS-008](task-0063) — ledger integration
9. [PKT-RLS-009](task-0064) — audit trail
10. [PKT-RLS-010](task-0065) — release validation
11. [PKT-RLS-011](task-0066) — release documentation

## Exit gate

- all release commands functional
- audit trails complete
- exactly-once semantics verified
- Release Please integrated

# Requirements

1. Release must be independent of jobs
2. Audit trails must be complete
3. Exactly-once semantics must be verified

# Constraints

- No job execution
- No provider execution
- No Discord delivery

# Acceptance Criteria

1. All release commands functional
2. Audit trails complete
3. Exactly-once verified
4. Release Please integrated
