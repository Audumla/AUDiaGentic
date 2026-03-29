# Phase 2 — Release, audit, ledger, Release Please

This phase builds the release subsystem as an independent core. It must work without jobs, Discord, or local AI. The only allowed inputs are tracked docs, runtime fragments, lifecycle/project config, and the managed Release Please baseline workflow/config.

## Phase deliverables

See the packet files for exact build steps.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.

## v12 corrective additions

Phase 2 now explicitly includes an end-to-end release-flow integration packet so the release core is proven before jobs depend on it.
