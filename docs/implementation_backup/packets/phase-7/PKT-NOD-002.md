# PKT-NOD-002 — Node heartbeat and status persistence

**Phase:** Phase 7

## Goal
Persist local node heartbeat/status under project-local runtime state.

## Dependencies
- `PKT-NOD-001`
- current job/provider status readers must be stable enough for safe summary queries

## Ownership boundary
- `src/audiagentic/nodes/heartbeat.py`
- `src/audiagentic/nodes/status.py`
- `tests/unit/nodes/test_heartbeat.py`

## Outputs
- `NodeHeartbeat`
- node status file layout under `.audiagentic/runtime/nodes/<node-id>/`

## Acceptance
- local heartbeat can be written/read atomically
- status derivation never mutates job/provider state
