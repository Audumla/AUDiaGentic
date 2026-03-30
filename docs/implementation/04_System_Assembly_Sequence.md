# System Assembly Sequence

## Why this sequence exists

AUDiaGentic is designed so later features layer on top of stable earlier seams. This document explains what each phase is allowed to assume and what it must not change.

## Assembly order

1. **Contracts first** — define schemas, ids, CLI envelopes, fixtures, validators.
2. **Lifecycle second** — make the system installable and project-scoped.
3. **Release core third** — make tracked docs and ledger behavior work without jobs.
4. **Jobs fourth** — jobs call the release core rather than owning release files directly.
5. **Providers fifth** — providers only attach to the job seam.
6. **Incremental .1 updates** — apply any post-gate contract or schema extensions.
7. **Provider model catalog** — model catalogs extend providers without changing job seams.
8. **Discord** — Discord only attaches to events and approvals.
9. **Migration hardening last** — harden rollout after core behavior exists.

## Forbidden redesigns by phase

- Phase 2 must not redesign lifecycle.
- Phase 3 must not redesign release file ownership.
- Phase 4 must not redesign job state.
- Phase 4.1 must not redesign provider selection or adapter contracts.
- Phase 5 must not redesign approvals or events.
- Phase 6 must not redesign earlier schemas.
