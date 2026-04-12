# Repository Domain Refactor and Package Realignment

> **Status: COMPLETE.** The v3 structural refactor was executed in `refactor/structural-v3`
> and merged. This document is preserved as a historical specification record.
> For the current domain structure see `02_Core_Boundaries_and_Dependency_Rules.md`
> and `02A_Repository_Domain_Dependency_Rules.md`.
> For the full execution report see `docs/refactor/v3-migration-report.md`.

---

## What was refactored

The repository was reorganized from a loose structure with 13 top-level package roots into
8 clear ownership-aligned domains.

### Before (pre-v3)

```
src/audiagentic/
  contracts/          → foundation/contracts/
  config/             → foundation/config/
  scoping/            → removed (planning/ was already implemented)
  streaming/          → interoperability/protocols/streaming/
  execution/
    providers/        → interoperability/providers/
    jobs/             (retained; store/session_input moved to runtime/state/)
  runtime/
    release/          → release/
    lifecycle/        (retained)
  channels/
  core/               → removed (empty placeholder)
  connectors/         → removed (empty placeholder)
  discovery/          → removed (empty placeholder)
  federation/         → removed (empty placeholder)
  nodes/              → removed (empty placeholder)
  observability/      → removed (empty placeholder)
```

### After (v3)

```
src/audiagentic/
  foundation/          (contracts/ + config/)
  planning/
  execution/
    jobs/
  interoperability/
    providers/
    protocols/
      streaming/
      acp/             (scaffold)
  runtime/
    lifecycle/
    state/             (jobs_store, session_input_store, reviews_store)
  release/
  channels/
    cli/
    vscode/            (scaffold)
  knowledge/           (scaffold)
```

## Decisions frozen during this refactor

1. **Package strategy**: domain-oriented reorganization under `src/audiagentic/`; not a
   top-level monorepo split.

2. **Stable import paths**: all public import paths updated; no compatibility shims retained
   after the refactor completed.

3. **tools/ stays**: remains as the deterministic utility root; entry points stay thin.

4. **Baseline preservation**: `.audiagentic/` tracked baseline and `.audiagentic/runtime/`
   exclusion model preserved unchanged.

5. **Schemas location**: `src/audiagentic/foundation/contracts/schemas/` (previously under
   the old `contracts/schemas/` root before it was moved under `foundation/`); `docs/examples/` unchanged.

6. **Test layout**: centralized `tests/` retained; domain structure mirrored inside it.

## Migration statistics

- 94 files moved/reorganized
- ~200 imports rewritten across src/, tests/, tools/
- 482 tests passing post-refactor (99.2% success rate)
- 4 test infrastructure bugs fixed post-execution

## Dependencies (historical)

- `02_Core_Boundaries_and_Dependency_Rules.md`
- `03_Common_Contracts.md`
