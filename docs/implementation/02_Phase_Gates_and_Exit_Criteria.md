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

## Phase 1 exit gate
- fresh install, update dispatch, cutover planning, uninstall planning all work in sandbox repos
- `.audiagentic/installed.json` manifest is written atomically and validates against schema
- `.audiagentic/` project-local config creation is deterministic
- managed workflow detection and rename policy is verified
- destructive sandbox tests demonstrate cleanup and recovery behavior
- document migration outcomes are emitted with reports

## Phase 2 exit gate
- release core works with no jobs and no providers
- duplicate fragment handling is deterministic
- sync is idempotent and lock-safe, including stale-lock recovery
- finalization writes checkpoints and is restart-safe
- Release Please baseline workflow/config management is deterministic
- end-to-end release flow integration tests pass using fixtures

## Phase 3 exit gate
- jobs run using local deterministic scripts only and stub/mock provider seam only
- workflow profiles validate and execute in order
- job approvals and timeouts use approval core
- jobs can update release docs only through release scripts

## Phase 4 exit gate
- provider selection is deterministic
- provider health check failures do not corrupt job state
- provider adapters fit the same contract
- packet runner integrates with real provider selection without altering Phase 3 job contracts
- optional server seam does not change default in-process execution

## Phase 5 exit gate
- Discord can be fully disabled
- no non-Discord component imports Discord code
- release summaries and approvals reach Discord via the event/approval contracts only

## Phase 6 exit gate
- legacy migration examples pass
- provider migration reports are deterministic
- cutover recovery runbooks are validated in sandbox repos
