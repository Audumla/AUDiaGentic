# PKT-RLS-002 — Sync current release ledger with lock and manifest

**Phase:** Phase 2  
**Primary owner group:** Release

## Goal

Implement fragment merge into `docs/releases/CURRENT_RELEASE_LEDGER.ndjson` with exclusive lock, duplicate handling, and manifest updates.

## Why this packet exists now

This packet is placed in Phase 2 because later packets depend on its outputs and must not redefine them.

## Dependencies

- `PKT-RLS-001`

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/release/sync.py`
- `tests/integration/release/test_sync.py`

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
def sync_current_release_ledger(ctx):
    with acquire_sync_lock(timeout=60, stale_after=300):
        fragments = list_pending_fragments(ctx)
        tracked = load_current_release_ledger(ctx)
        merged = merge_by_event_id(tracked, fragments)
        atomic_write_ndjson(ctx.current_release_ledger, merged)
        write_sync_manifest(ctx, merged)
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

- fragment set and stale-lock fixtures

## Tests to add

- sync is idempotent and lock-safe
- add one failure-path test proving the packet does not corrupt owned state on error
- add one repeat-run/idempotency test if the packet writes durable files

## Acceptance criteria

- tracked current ledger sync implemented
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


## Lock file specification

The sync lock lives at:

```text
.audiagentic/runtime/ledger/sync/lock.json
```

### Lock file format

```json
{
  "pid": 12345,
  "hostname": "localhost",
  "acquired-at": "2026-03-29T00:00:00Z",
  "command": "sync-current-release-ledger"
}
```

### Required stale-lock handling

- acquisition timeout: 60 seconds
- stale-after threshold: 300 seconds
- stale detection must check PID liveness when feasible
- if PID is dead or age exceeds threshold, replace the lock and emit a warning event
- all lock replacement behavior must be covered by integration tests

### Required example fixtures

Add:
- `docs/examples/fixtures/ledger-fragment.sample.json`
- `docs/examples/fixtures/current-release.sample.md`
- `docs/examples/fixtures/ledger-lock.stale.json`
