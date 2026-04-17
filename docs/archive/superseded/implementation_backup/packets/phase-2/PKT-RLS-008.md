# PKT-RLS-008 — End-to-end release flow integration tests

**Phase:** Phase 2  
**Primary owner group:** Release

## Goal

Prove the full release flow works end-to-end from fragment capture through sync, summary generation, and finalization.

## Dependencies

- `PKT-RLS-001`
- `PKT-RLS-002`
- `PKT-RLS-003`
- `PKT-RLS-004`
- `PKT-RLS-005`
- `PKT-RLS-006`
- `PKT-RLS-007`

## Ownership boundary

Owns:
- `tests/integration/release/test_end_to_end_release_flow.py`

## Detailed build steps

1. Build fixtures for multiple fragments.
2. Run sync once and assert tracked outputs.
3. Run sync again and assert idempotency.
4. Run finalization and assert checkpoints.
5. Simulate interruption and rerun finalization.
6. Assert no duplicate historical append occurs.

## Acceptance criteria

- release flow passes from fragment to finalization
- rerun after interruption is safe
- no duplicate append occurs in `LEDGER.ndjson`
