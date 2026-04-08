# PKT-EVT-001 — Node event families and publisher extension

**Phase:** Phase 9

## Goal
Extend event publication with node-level events and normalized node heartbeat records.

## Dependencies
- Phase 7 VERIFIED
- Phase 8 static registry baseline VERIFIED

## Ownership boundary
- `src/audiagentic/eventing/node_events.py`
- `tests/unit/eventing/test_node_events.py`

## Acceptance
- node events append locally first
- remote publication is additive only
