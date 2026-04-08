# PKT-JOB-007 — Incremental job updates for provider model selection

**Phase:** Phase 3.1  
**Primary owner group:** Jobs

## Goal

Extend job metadata and validation to support provider model selection without altering Phase 3 workflow semantics.

## Why this packet exists now

Provider model catalog work introduces model-id and alias resolution. Jobs must carry those fields safely and validate them without changing job state machine behavior.

## Dependencies

- Phase 3 gate `VERIFIED`
- `PKT-PRV-012` once model selection rules are finalized

## Concrete job inputs

This packet must support the following job-level model selection data:

- `provider-id`
- `model-id`
- `model-alias`
- `default-model`

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/execution/jobs/*`
- job tests under `tests/unit/jobs/` and `tests/integration/jobs/`

### It may read from
- provider model catalog contracts
- workflow profile contracts

### It must not edit directly
- provider selection logic
- release core or lifecycle modules
- contract schemas (owned by `PKT-FND-008`)

## Detailed build steps

1. Identify the exact job record fields required for model selection.
2. Update job validation logic to accept the new fields and preserve them in storage.
3. Ensure packet runner passes model selection inputs to provider selection layer.
4. Keep existing job state transitions unchanged.
5. Add tests to validate job records with model selection inputs.

## Integration points

- `src/audiagentic/execution/jobs/records.py`
- `src/audiagentic/execution/jobs/store.py`
- `src/audiagentic/execution/jobs/state_machine.py`
- `src/audiagentic/execution/jobs/packet_runner.py`
- `src/audiagentic/execution/jobs/stages.py`
- `src/audiagentic/execution/jobs/release_bridge.py`

## Tests to add or update

- job record validation tests for model-id/alias
- packet runner integration tests to ensure model fields pass through

## Acceptance criteria

- jobs accept and persist model selection metadata
- no changes to job state machine semantics
- tests cover model selection metadata paths
- packet runner forwards selection metadata cleanly to providers

## Recovery procedure

If this packet fails mid-implementation:
- revert job changes
- rerun `python -m pytest tests/unit/jobs tests/integration/jobs`

## Parallelization note

This packet may run in parallel only with work that does not touch job modules.

## Out of scope

- provider catalog fetch/refresh logic
- contract schema changes (owned by `PKT-FND-008`)
