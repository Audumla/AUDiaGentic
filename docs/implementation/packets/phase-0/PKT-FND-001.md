# PKT-FND-001 — Canonical id table and naming validator

**Phase:** Phase 0  
**Primary owner group:** Contracts

## Goal

Freeze all provider/component/schema ids and create the validator that prevents naming drift.

## Why this packet exists now

This packet is placed in Phase 0 because later packets depend on its outputs and must not redefine them.

## Dependencies

- None

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/contracts/canonical_ids.py`
- `src/audiagentic/contracts/glossary.py`
- `tools/validate_ids.py`
- `tests/unit/contracts/test_validate_ids.py`

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
6. Do not introduce runtime behavior in this packet unless explicitly listed.
7. If a schema or canonical id changes, update fixtures and validators in the same change.

## Pseudocode

```python
def validate_ids(paths):
    forbidden = load_forbidden_aliases()
    findings = scan_tree(paths, forbidden)
    if findings:
        emit_json(status="error", findings=findings)
        return 2
    emit_json(status="ok", findings=[])
    return 0
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

- canonical-id fixtures

## Tests to add

- validator returns 0 on canonical tree
- validator returns non-zero on bad variants
- add one failure-path test proving the packet does not corrupt owned state on error
- add one repeat-run/idempotency test if the packet writes durable files

## Acceptance criteria

- canonical id table frozen
- validator in CI
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
