# 49 — Phase 7 Node Execution Extension Build Book

## Goal

Add a node execution model to AUDiaGentic without changing single-node correctness.

## Why this phase exists

The current backend already supports lifecycle, jobs, prompt launch, job control, session input, provider status, and an optional service boundary.
That is enough to justify an additive node model rather than a rewrite.

## Deliverables

- node descriptor contract
- node heartbeat contract
- node-local job ownership additive fields
- node runtime module skeleton
- node status CLI/API surface
- node-local persistence under `.audiagentic/runtime/nodes/`

## Dependency rule

This phase starts only after the current Phase 4 active provider/runtime work is stabilized enough that node status can query provider/job/session state without redesigning those subsystems.

## Recommended module additions

```text
src/audiagentic/nodes/
  identity.py
  heartbeat.py
  status.py
  registry.py
  ownership.py
  api.py
```

## Phase exit gate

This phase is complete when:
- a node can describe itself
- a node can emit heartbeat/status locally
- local jobs can be associated with a node
- no UI or discovery provider is required
