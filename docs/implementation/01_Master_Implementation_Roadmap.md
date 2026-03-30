# Master Implementation Roadmap

> **Build status registry requirement:** all packet and phase execution must be tracked in `31_Build_Status_and_Work_Registry.md`. That registry is the live operational source of truth for what is done, what is active, and what may start next.


## Program goal

Build AUDiaGentic from a minimal correct baseline up to the agreed end-state capability without forcing rewrites of previously finished core components.

## Delivery doctrine

- Freeze contracts before behavior.
- Build independent cores before overlays.
- Prefer script-backed deterministic behavior before AI-assisted behavior.
- Keep jobs simple before introducing richer orchestration.
- Keep Discord out of the core.
- Keep providers out of the release/lifecycle core until their phase.
- Make each packet small enough for one implementor or one agent.

## End-to-end build sequence

### Phase 0 — Contracts and scaffolding
Build everything needed so later packets can code against frozen shapes rather than prose.

Leaves behind:
- canonical ids
- glossary
- schemas
- fixtures
- validators
- lifecycle CLI stub
- example project scaffold

### Phase 0.1 — Incremental contract enhancements
Capture follow-on contract/schema updates discovered after Phase 0 gate closes.

Leaves behind:
- updated schemas/fixtures for new contracts introduced by later phases
- validation updates required by new tracked config fields

### Phase 1 — Lifecycle and project enablement
Build installation, update, cutover, uninstall, and project enablement into `.audiagentic/`.

Leaves behind:
- deterministic lifecycle dispatcher
- installed-state detection
- project-local config creation
- migration reports
- managed workflow file handling

### Phase 1.1 — Incremental lifecycle enhancements
Capture follow-on lifecycle updates needed by later phases without redesigning Phase 1 seams.

Leaves behind:
- lifecycle validation extensions required by new contracts
- incremental install/update behavior fixes tied to new config fields

### Phase 2 — Release / audit / ledger / Release Please
Build the release core independent of jobs.

Leaves behind:
- fragment capture
- sync with locking and idempotency
- current release summary
- audit/check-in summary generation
- finalization with exactly-once historical append
- Release Please baseline workflow/config management

### Phase 2.1 — Incremental release/ledger enhancements
Capture release/ledger updates required by later phases while keeping Phase 2 contracts stable.

Leaves behind:
- ledger or summary tweaks needed for new contracts
- additional deterministic release artifacts required by later phases

### Phase 3 — Jobs and simple workflows
Build a simple job engine that uses the release core instead of reimplementing it.

Leaves behind:
- job records and store
- state machine
- workflow profiles
- packet runner
- approval handling inside jobs
- release bridge from jobs to scripts

### Phase 3.1 — Incremental job enhancements
Capture job-layer updates required by later phases without redesigning Phase 3 seams.

Leaves behind:
- new job validation or metadata required by providers or overlays
- additional job artifacts required by model catalog and selection

### Phase 3.2 — Prompt-tagged workflow launch and review loop
Add a prompt-tag driven launch path that can create or resume workflow activities from CLI or VS Code prompts.

Leaves behind:
- prompt tag resolution for workflow activities
- review-stage feedback loop artifacts
- cross-prompt handoff rules for plan/implement/review

### Phase 4 — Providers and optional server seam
Add providers and an optional extraction boundary without changing earlier cores.

Leaves behind:
- provider registry
- health checks
- deterministic provider selection
- provider adapters
- optional service seam that can be ignored by default

### Phase 4.1 — Provider model catalog and selection
Extend provider capabilities with explicit model catalogs and model selection rules.

Leaves behind:
- provider model catalog contract
- model alias and selection resolution
- catalog refresh CLI
- provider documentation updates for model guidance

### Phase 5 — Discord overlay
Add Discord as a true overlay using approval + events only.

Leaves behind:
- event subscriber
- release summary publishing
- approval publishing/response handling
- lifecycle/migration notices

### Phase 6 — Migration hardening and cutover completion
Harden migration and operator recovery.

Leaves behind:
- migration fixtures and examples
- provider migration rules
- cutover runbooks
- hardened cutover/uninstall validation

## Phase gates

Each phase has a hard exit gate. The next phase must not start until the prior phase leaves behind the artifacts documented in `02_Phase_Gates_and_Exit_Criteria.md`.

## Parallelization rule

Parallel work is allowed only when:
- packet dependencies are satisfied,
- ownership does not overlap,
- shared contracts are already frozen,
- and the module ownership map shows no collision.


## Corrective additions in v12

The implementation reviews identified a small set of items that are important enough to formalize before coding proceeds:

- **CI/CD and testing infrastructure** is a required Phase 0 companion, not an implicit assumption.
- **Packet dependency graph** is now treated as a first-class readiness artifact so teams do not start work on incomplete transitive prerequisites.
- **Lifecycle manifest format** is now explicitly pinned in the lifecycle packet set.
- **Error envelope and error-code registry** are now phase-owned contract outputs.
- **Destructive sandbox testing** is mandatory before any lifecycle packet crosses a destructive boundary.
- **Phase 3 jobs use a stub provider seam**; real provider integration is deferred to Phase 4 to avoid core rewrites.

These additions do not change the sequence of phases. They tighten execution discipline within the existing sequence.
