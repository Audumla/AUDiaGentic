# Phase 1 — Lifecycle and project enablement

This phase makes AUDiaGentic installable and removable in a project without touching release or job logic yet. It creates project enablement, installed-state detection, lifecycle dispatch, migration reporting, and the rules for preserving tracked documents and cleaning runtime state.

## Phase deliverables

See the packet files for exact build steps.

Phase 1.3 is a lifecycle follow-on packet for provider auto-install policy persistence. It does not
change lifecycle behavior; it only keeps new provider install/bootstrap policy fields round-trippable
through project install and migration flows.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.

## Follow-on packet

- `PKT-LFC-010` — provider auto-install policy persistence and lifecycle roundtrip
