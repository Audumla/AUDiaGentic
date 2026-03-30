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

## Phase 3 exit gate
- jobs run using local deterministic scripts only and stub/mock provider seam only
- workflow profiles validate and execute in order
- job approvals and timeouts use approval core
- jobs can update release docs only through release scripts

## Phase 3.1 exit gate
- job metadata extensions required by providers are validated
- packet runner behavior remains unchanged for Phase 3 contracts

## Phase 3.2 exit gate
- prompt-tag launch resolves to a deterministic workflow activity
- CLI and VS Code prompt surfaces preserve source provenance on launched jobs
- review stage can consume another agent's work artifact and emit actionable feedback
- plan/implement/review handoffs remain deterministic and testable

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

## Phase 5 exit gate
- Discord can be fully disabled
- no non-Discord component imports Discord code
- release summaries and approvals reach Discord via the event/approval contracts only

## Phase 6 exit gate
- legacy migration examples pass
- provider migration reports are deterministic
- cutover recovery runbooks are validated in sandbox repos
