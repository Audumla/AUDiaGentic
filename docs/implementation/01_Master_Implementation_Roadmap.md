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


### Phase 0.2 — Prompt/review contract extension
Capture the additive contract, schema, and fixture work required by prompt-tagged launch and structured review without reopening base Phase 0 design.

Leaves behind:
- prompt launch envelope contract
- review report and review bundle contracts
- prompt-launch policy block in ProjectConfig
- fixtures for ad hoc targets and multi-review aggregation

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


### Phase 1.2 — Incremental lifecycle updates for prompt launch
Capture tracked-config preservation and validation needed by prompt-launch policy fields.

Leaves behind:
- lifecycle validation for prompt-launch policy fields
- stable `.audiagentic/project.yaml` handling for workflow overrides and review policy

### Phase 1.3 — Provider auto-install policy persistence
Capture tracked-config preservation and validation needed by provider auto-install and bootstrap policy fields.

Leaves behind:
- lifecycle validation for provider auto-install policy fields
- stable `.audiagentic/providers.yaml` and `.audiagentic/project.yaml` handling for install/bootstrap policy fields

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


### Phase 2.2 — Incremental release/ledger updates for prompt/review metadata
Capture deterministic omission/summarization rules for prompt provenance and review outputs.

Leaves behind:
- explicit release/audit handling for prompt/review metadata
- deterministic check-in summary rules for review outcomes

### Phase 2.3 — Project release bootstrap and workflow activation
Use the project's own release machinery to bootstrap or refresh the project-local release workflow state so the repository can install and refresh itself with the same tracked release processes it already owns.

Leaves behind:
- project-local release workflow activation
- bootstrap of `.audiagentic/installed.json` and managed Release Please workflow/config state
- preservation of existing tracked provider config during bootstrap/update
- audit/check-in/current-release regeneration through the release subsystem

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
Add a prompt-tag driven launch path that can create or resume workflow activities from CLI or VS Code prompts, including generic ad hoc work and deterministic multi-review.

Leaves behind:
- prompt tag resolution for workflow activities
- normalized prompt launch envelope
- ad hoc target handling
- structured review reports and review bundles
- cross-prompt handoff rules for plan/implement/review
- deterministic multi-review aggregation

### Phase 3.3 — Prompt shorthand and default-launch enhancement
Add ergonomic shorthand for prompt launch so a provider or short tag can be used without spelling out the full target block, while preserving the same normalized launch path.

Leaves behind:
- short action aliases for launch tags
- provider shorthand launch parsing
- default subject generation when target is omitted

### Phase 3.4 — Job control and running-job cancellation
Add a dedicated job-control path so pending, awaiting-approval, and actively running jobs can be cancelled deterministically without changing the prompt-launch contract.

Leaves behind:
- job-control request and runtime record
- cooperative stop checks for running jobs
- running-job cancellation state transitions
- cancel/stop CLI or service surface
- provider-default model resolution in launch flow
- prompt-launch ergonomics tests and docs


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

### Phase 4.2 — Provider status and validation
Track provider status inspection, config validation, CLI availability checks, and catalog presence reporting without changing model-selection or surface rules.

Leaves behind:
- provider status CLI / validation command
- CLI availability reporting
- catalog presence and health reporting
- deterministic config diagnostics for provider-backed surfaces

### Phase 4.3 — Provider prompt-tag surface integration
Add shared prompt-tag recognition and provider-surface synchronization so CLI and VS Code surfaces can normalize tagged prompts into the frozen launch contract.

Leaves behind:
- shared prompt-tag surface contract
- provider config/descriptor prompt-surface fields
- provider-specific surface settings profiles
- prompt-tag surface rollout packets per provider

### Phase 4.4 — Provider tag execution compliance and isolated provider implementation docs
Add a provider-execution compliance model and per-provider implementation guides so each provider can be implemented and tested independently without changing the shared grammar.

Leaves behind:
- provider execution compliance model
- provider conformance matrix
- isolated provider implementation docs
- provider-specific settings and smoke-test guidance
- native-intercept / mapped-execution / backend-only classification notes

### Phase 4.6 — Provider prompt-trigger launch behavior
Add provider-owned prompt-trigger bridges and wrapper/instruction surfaces so a tagged prompt can actually launch the shared workflow runner from each provider's local integration path.

Leaves behind:
- shared prompt-trigger launch contract
- provider instruction/bridge surface matrix
- realistic provider rollout assessment
- wrapper fallback and repo bridge guidance
- provider-specific launch packets and smoke tests
- a stable hook between provider instruction surfaces and `prompt-launch`

### Phase 4.7 — Provider availability and auto-install orchestration
Add provider availability checks and opt-in auto-install/bootstrap behavior so missing providers can be configured or prepared during project install instead of failing only at launch time.

Leaves behind:
- shared provider availability and install-policy contract
- provider-specific install/bootstrapping guidance
- repo-local bootstrap and re-check harness
- install policy packets per provider
- project-local install configuration examples

### Phase 4.9 — Provider live stream and progress capture
Add AUDiaGentic-owned live output capture so provider progress can be mirrored to the console and persisted in runtime artifacts without moving persistence responsibility into the provider.

Leaves behind:
- shared live-stream and progress capture contract
- normalized progress event records
- console mirroring switches and runtime output layout
- Cline and Codex first-wave capture packets
- later Discord stream-consumption guidance

### Phase 4.10 — Provider live input and interactive session control
Add AUDiaGentic-owned session-input capture so follow-up prompts, pause/resume instructions, and conversational turns can be injected into a live job session without moving session control responsibility into the provider.

Leaves behind:
- shared live-input and interactive-session control contract
- normalized session-input event records
- console input and runtime input capture switches
- Cline and Codex first-wave interactive-session packets
- later Discord input-consumption guidance

### Phase 4.11 — Provider structured completion and result normalization
Add a shared canonical completion/result contract so each provider can return its final review or execution result through the most stable available native surface without duplicating the shared bridge or capture harness.

Leaves behind:
- shared structured completion and result normalization contract
- canonical final-result payload shape
- provider-specific preferred completion methods
- Cline/Codex first-wave normalization guidance
- later provider result-completion rollout guidance

### Phase 4.12 — Provider optimization and shared workflow extensibility
Add shared optimization seams so repetitive text scanning, editing, summarization, and workflow handoff mechanics can move into scripts, skills, MCP tools, or wrapper helpers without locking the project into a single future workflow engine.

Leaves behind:
- shared optimization and reuse contract
- reusable file scan / patch / summarize helpers
- skill / MCP / wrapper extension points
- future workflow/task tracker seam
- provider-neutral token-reduction guidance

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
