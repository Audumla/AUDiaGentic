# Phase 1 — Lifecycle and project enablement

This phase makes AUDiaGentic installable and removable in a project without touching release or job logic yet. It creates project enablement, installed-state detection, lifecycle dispatch, migration reporting, and the rules for preserving tracked documents and cleaning runtime state.

## Phase deliverables

See the packet files for exact build steps.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.
