# Phase 5 — Discord overlay

Discord is built last as an optional overlay. It consumes events and approval state from the core but must not become a transitive dependency of lifecycle, release, or jobs. The overlay can be disabled entirely with no functional loss to core behavior.

## Phase deliverables

See the packet files for exact build steps. Phase 4.4 must be verified before this phase is claimed.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.
