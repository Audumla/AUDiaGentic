# Phase 3 — Jobs and simple workflows

This phase introduces the job engine, but keeps it intentionally simple. The job engine must consume frozen contracts from earlier phases and must use the release scripts instead of reimplementing release logic internally. Only `lite`, `standard`, and `strict` workflow profiles are in scope.

## Phase deliverables

See the packet files for exact build steps.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.
