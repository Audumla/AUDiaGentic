# PKT-RLS-005 — Finalize release with exactly-once historical append

**Phase:** Phase 2  
**Primary owner group:** Release

## Goal

Implement release finalization checkpoints, recovery, and exactly-once append to the historical ledger.

## Why this packet exists now

This packet is placed in Phase 2 because later packets depend on its outputs and must not redefine them.

## Dependencies

- `PKT-RLS-002`
- `PKT-RLS-003`
- `PKT-RLS-004`

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/release/finalize.py`
- `tests/e2e/release/test_finalize.py`

### It may read from
- frozen contracts in `docs/specifications/architecture/`
- approved fixtures under `docs/examples/fixtures/`
- outputs from dependency packets only

### It must not edit directly
- files owned by other groups unless a dependency explicitly requires it
- tracked release docs outside the owned writer module
- contract schemas unless this packet is in the contracts ownership chain

## Public contracts used

- schemas and shapes from `docs/specifications/architecture/03_Common_Contracts.md`
- phase gates from `docs/implementation/02_Phase_Gates_and_Exit_Criteria.md`
- ownership rules from `docs/implementation/05_Module_Ownership_and_Parallelization_Map.md`

## Detailed build steps

1. Create the module skeletons and test files listed in the ownership set.
2. Implement the core data structures and pure functions first.
3. Add fixtures that prove the contract before wiring the CLI or orchestration layer.
4. Add the thinnest possible wrapper needed to expose the behavior to the rest of the system.
5. Run unit tests, then integration tests, then update the packet checklist and owned outputs.
6. Do not write tracked release docs directly from tests or helper scripts; only via the owned module.
7. Preserve idempotency by designing writes as full regenerations or atomic appends, never in-place mutation.

## Pseudocode

```python
def finalize_release(ctx):
    cp = load_finalize_checkpoints(ctx)
    if not cp.synced: sync_current_release_ledger(ctx)
    if not cp.summaries: regenerate_current_release(ctx); generate_audit_and_checkin(ctx)
    outputs = prepare_release_outputs(ctx)
    if not cp.historical_append_done: append_historical_once(ctx, outputs.events)
    write_tracked_release_docs(ctx, outputs)
    reset_current_cycle(ctx)
```

## Detailed implementation notes

### Data flow
1. Inputs are loaded from project-local config, runtime state, or fixtures.
2. Core logic is executed in library code under `src/audiagentic/`.
3. Outputs are written atomically to owned files only.
4. Tests verify both the output content and the side-effect boundaries.

### Error handling
- Return machine-readable errors through the standard CLI envelope where applicable.
- Distinguish validation failures from business-rule failures.
- Never partially write owned tracked files; use temp-file + atomic replace when the contract requires it.

### Extension seam left behind
This packet must leave behind a seam that later phases can reuse without changing the packet’s public output format.

## Fixtures to add

- partial-finalize checkpoint fixtures

## Tests to add

- finalize is restart-safe and historical append occurs once
- add one failure-path test proving the packet does not corrupt owned state on error
- add one repeat-run/idempotency test if the packet writes durable files

## Acceptance criteria

- LEDGER.ndjson, CHANGELOG.md, RELEASE_NOTES.md, VERSION_HISTORY.md update flow implemented
- all owned tests pass in isolation
- packet outputs are deterministic across repeated runs with the same inputs
- no file outside the ownership boundary changes during the packet test run unless listed explicitly

## Deliverables / artifacts left behind
- production modules listed in ownership boundary
- tests and fixtures listed above
- updated implementation checklist entry in the phase build book if needed

## Parallelization note

This packet may run in parallel only after all dependencies are merged and only with packets whose ownership boundary does not overlap this packet.

## Out of scope

- redesigning contracts owned by earlier packets
- adding future-phase behavior not required for this packet’s acceptance criteria
- solving provider/Discord/server concerns unless explicitly part of this packet
