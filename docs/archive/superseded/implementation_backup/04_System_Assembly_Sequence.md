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
10. **Node execution extension** — add node identity, heartbeat, and ownership after provider/runtime stabilization.
11. **Discovery and registry extension** — add pluggable locator providers after node contracts are stable.
12. **Federation and control extension** — add node-side federation/event/control seams after registry and node status are stable.
13. **Coordinator consumption seam** — expose backend-only coordinator query/control seams without adding UI dependence.
14. **External tool connectivity** — add optional external connectors last, after the node/discovery/federation seams are stable.

## Forbidden redesigns by phase

- Phase 2 must not redesign lifecycle.
- Phase 1.4 may refine how lifecycle/bootstrap apply the managed project baseline, but it must do so by converging install/bootstrap onto one shared sync seam rather than creating a second installer model.
- Phase 3 must not redesign release file ownership.
- Phase 4 must not redesign job state.
- Phase 4.1 must not redesign provider selection or adapter contracts.
- Phase 5 must not redesign approvals or events.
- Phase 6 must not redesign earlier schemas.
- Phase 7 must not redesign provider/runtime contracts.
- Phase 8 must not introduce mandatory discovery dependencies.
- Phase 9 must preserve node-local truth.
- Phase 10 must stay backend-only and UI-free.
- Phase 11 must remain optional and non-authoritative.
