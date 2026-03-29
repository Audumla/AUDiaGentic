# Phase 4 — Providers and optional server seam

This phase adds provider-driven execution without destabilizing the core. The provider seam is added on top of the job system, and the optional server seam is defined as a thin extraction boundary only. In-process execution remains the default and must stay first-class.

## Phase deliverables

See the packet files for exact build steps.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.

## v12 corrective additions

Phase 4 now includes an explicit job/provider seam integration packet so provider attachment can be verified without rewriting Phase 3 job contracts.

Phase 4 uses **deterministic provider selection with no automatic failover in MVP**. Failover remains a DRAFT later enhancement.
