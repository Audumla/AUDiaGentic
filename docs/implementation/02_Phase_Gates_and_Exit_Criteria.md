# Phase Gates and Exit Criteria

## Phase 0 exit gate
- schema validator runs in CI
- naming validator runs in CI
- lifecycle stub emits deterministic `plan`, `apply`, `validate` output in dry-run/test mode
- all fixtures validate or fail as expected
- error envelope and error-code registry are frozen
- CI matrix covers unit, contract, fixture, and destructive-plan tests
- packet dependency graph is published and all Phase 0 packets have no unresolved transitive blockers
- no packet in later phases needs to change contract fields

## Phase 0.1 exit gate
- any new schemas or fixtures introduced by later phases validate in CI
- validators updated for new contract fields
- change log recorded with contract update rationale


## Phase 0.2 exit gate
- PromptLaunchRequest, ReviewReport, and ReviewBundle contracts exist with schemas and fixtures
- ProjectConfig schema validates `prompt-launch` and `workflow-overrides` fields
- fixtures cover `target.kind=adhoc` and distinct-reviewer counting inputs
- change log recorded with prompt/review contract rationale

## Phase 1 exit gate

- fresh install, update dispatch, cutover planning, uninstall planning all work in sandbox repos
- `.audiagentic/installed.json` manifest is written atomically and validates against schema
- `.audiagentic/` project-local config creation is deterministic
- managed workflow detection and rename policy is verified
- destructive sandbox tests demonstrate cleanup and recovery behavior
- document migration outcomes are emitted with reports

## Phase 1.1 exit gate
- lifecycle validation covers any new config fields required by later phases
- no breaking changes to Phase 1 contracts or install artifacts


## Phase 1.2 exit gate
- lifecycle validation preserves prompt-launch policy fields in `.audiagentic/project.yaml`
- no breaking changes to Phase 1 lifecycle artifacts
- fresh install/update tests prove fields are retained deterministically

## Phase 1.3 exit gate
- lifecycle validation preserves provider auto-install policy fields in tracked config
- no breaking changes to Phase 1 lifecycle artifacts
- fresh install/update/cutover tests prove the fields are retained deterministically

## Phase 2 exit gate

- release core works with no jobs and no providers
- duplicate fragment handling is deterministic
- sync is idempotent and lock-safe, including stale-lock recovery
- finalization writes checkpoints and is restart-safe
- Release Please baseline workflow/config management is deterministic
- end-to-end release flow integration tests pass using fixtures

## Phase 2.1 exit gate
- release artifacts updated for new contract fields without changing Phase 2 schemas
- ledger sync and summary remain deterministic after updates


## Phase 2.2 exit gate
- release and audit outputs explicitly omit or summarize prompt/review metadata according to policy
- no raw prompt text or raw review bundles are written into tracked release docs by default
- check-in summaries remain deterministic after review outcome handling is added

## Phase 2.3 exit gate
- project-local release bootstrap writes or refreshes installed state deterministically
- managed Release Please workflow/config state is prepared through the project's own release machinery
- existing tracked provider config is preserved during bootstrap/update
- audit, check-in, and current-release docs regenerate deterministically after bootstrap

## Phase 3 exit gate

- jobs run using local deterministic scripts only and stub/mock provider seam only
- workflow profiles validate and execute in order
- job approvals and timeouts use approval core
- jobs can update release docs only through release scripts

## Phase 3.1 exit gate
- job metadata extensions required by providers are validated
- packet runner behavior remains unchanged for Phase 3 contracts

## Phase 3.2 exit gate
- `prefix-token-v1` prompt syntax is enforced deterministically
- prompt-tag launch resolves to a deterministic workflow activity and legal target kind
- `@adhoc` creates a valid generic job subject without pretending to be a packet
- CLI and VS Code prompt surfaces preserve source provenance on launched jobs
- review stages emit `ReviewReport` artifacts and aggregate into a deterministic `ReviewBundle`
- multi-review `all-pass` policy is testable and blocks progression on `rework` or `block`
- plan/implement/review handoffs remain deterministic and testable

## Phase 3.3 exit gate
- short action aliases resolve deterministically to the same workflow tags
- provider shorthand launches resolve to provider defaults without changing the normalized request contract
- omitted targets generate a sensible default subject and job id
- provider-default model resolution is preserved through launch and resume paths
- shorthand/default-launch behavior is covered by parser, launch, and integration tests

## Phase 3.4 exit gate
- job-control requests are recorded in a stable runtime artifact
- running jobs can transition to cancelled through a deterministic control path
- stage outputs written before cancellation remain visible
- cancellation does not change prompt-launch or provider execution semantics

## Phase 4 exit gate
- provider selection is deterministic
- provider health check failures do not corrupt job state
- provider adapters fit the same contract
- packet runner integrates with real provider selection without altering Phase 3 job contracts
- optional server seam does not change default in-process execution

## Phase 4.1 exit gate
- provider model catalog contract and schema exist with fixtures
- model selection resolves explicit model-id, alias, and default deterministically
- catalog refresh command writes runtime catalog atomically
- provider documentation includes model catalog guidance

## Phase 4.2 exit gate
- provider status CLI reports config health, CLI availability, and catalog presence
- config validation fails cleanly for unsupported or malformed provider surface settings
- no prompt-tag surface semantics are introduced yet

## Phase 4.3 exit gate
- provider config and descriptor schemas include prompt-surface fields
- provider surfaces normalize prompt tags using the shared surface contract
- provider-specific surface settings profiles are documented and synchronized
- prompt-tag surface changes still preserve jobs-layer validation and provenance

## Phase 4.4 exit gate
- provider execution compliance model and conformance matrix are frozen
- provider-specific implementation docs stay isolated per provider
- native-intercept, mapped-execution, and backend-only classifications are documented per provider
- no shared prompt grammar changes are required to start provider-specific execution work

## Phase 4.6 draft gate
- shared trigger grammar and launcher bridge contract are written down
- provider instruction surfaces are named for each supported provider
- wrapper fallback rules are documented for providers without a stable native intercept path
- the realistic provider-by-provider rollout assessment is recorded before implementation starts
- provider-specific launch packets exist before implementation begins

## Phase 4.7 draft gate
- shared provider availability and install-policy contract is written down
- provider install/bootstrap surfaces are named for each supported provider
- auto-install remains opt-in and project-local
- provider-specific install packets exist before implementation begins

## Phase 4.9 draft gate
- shared live-stream and progress capture contract is written down
- provider capture surfaces are named for the first-wave providers, starting with Cline and Codex
- console mirroring and runtime persistence are owned by AUDiaGentic, not the provider
- provider-specific live-stream packets exist before implementation begins
- Discord remains a later consumer of the same stream contract

## Phase 4.10 draft gate
- shared live-input and interactive-session control contract is written down
- provider input surfaces are named for the first-wave providers, starting with Cline and Codex
- console input capture and runtime persistence are owned by AUDiaGentic, not the provider
- provider-specific live-input packets exist before implementation begins
- Discord remains a later consumer of the same input contract

## Phase 4.11 draft gate
- shared structured completion and result normalization contract is written down
- provider completion surfaces are named for the first-wave providers, starting with Cline and Codex
- final artifact persistence is owned by AUDiaGentic, not the provider
- provider-specific result-normalization guidance exists before implementation begins
- Discord and later overlays remain later consumers of the same normalized completion contract

## Phase 4.12 draft gate
- shared optimization and reuse contract is written down
- provider-neutral helper seams for file scanning, patching, and summarization are named
- skill, MCP, and wrapper extension points are documented without forcing a single implementation technology
- the future workflow/task tracker remains intentionally undefined but not blocked
- provider-specific token-reduction guidance exists before implementation begins

## Phase 5 exit gate
- Phase 4.4 gate is verified and provider execution docs are frozen
- Discord can be fully disabled
- no non-Discord component imports Discord code
- release summaries and approvals reach Discord via the event/approval contracts only

## Phase 6 exit gate
- legacy migration examples pass
- provider migration reports are deterministic
- cutover recovery runbooks are validated in sandbox repos
