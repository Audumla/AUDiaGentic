# Change Control and Document Update Rules

## Purpose

Stop silent drift between packets, implementation, and contracts.

## Rules

1. If implementation diverges from a contract, stop and raise a contract change request.
2. If implementation diverges only from packet detail, update the packet in the same change.
3. Do not silently modify shared schemas, ids, or tracked file ownership.
4. Cross-packet refactors require owner approval from all affected groups.

## Documentation update rule

When a packet changes documented behavior:
- update the packet build sheet
- update fixtures/examples affected
- update implementation guidance if execution order or recovery changes
- update architecture only when the contract changes

## Recovery section requirement

New packets added after v12 should include:
- recovery procedure for failed partial implementation
- files to delete/reset before rerun
- tests to rerun after recovery

## DRAFT future enhancements

- ADR fast-track for obvious contract bugs
- automated doc drift detection
