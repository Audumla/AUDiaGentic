# PKT-NOD-003 — Node-aware job ownership fields

**Phase:** Phase 7

## Goal
Add additive job record fields for node ownership and execution mode.

## Dependencies
- `PKT-NOD-001`
- `PKT-JOB-001`
- `PKT-JOB-011` state must be stable enough to avoid reopening control semantics

## Ownership boundary
- `src/audiagentic/execution/jobs/records.py`
- `src/audiagentic/execution/jobs/store.py`
- `tests/unit/jobs/test_node_ownership_fields.py`

## Fields
- `origin-node-id`
- `assigned-node-id`
- `execution-mode`
- `coordination-scope`

## Acceptance
- additive only
- older jobs remain readable
- local-only behavior remains unchanged when fields are absent
