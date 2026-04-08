# PKT-EVT-002 — Node control request contract

**Phase:** Phase 9

## Goal
Define node control requests such as drain, resume, quarantine, assign-job, release-job.

## Dependencies
- `PKT-EVT-001`
- node identity and ownership fields implemented

## Acceptance
- control requests are validated locally
- no coordinator may bypass node-side ownership checks
