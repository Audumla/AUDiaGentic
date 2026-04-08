# PKT-CRD-001 — Coordinator consumption seam

**Phase:** Phase 10

## Goal
Expose a stable AUDiaGentic-side query/control seam for coordinators and boards.

## Dependencies
- Phase 9 VERIFIED
- optional server seam remains additive

## Ownership boundary
- `src/audiagentic/channels/server/node_api.py`
- `tests/integration/server/test_node_api.py`

## Acceptance
- a coordinator can list nodes and query jobs/sessions/workspaces
- no UI concerns are introduced into core AUDiaGentic modules
