# Acceptance Matrix and Destructive Test Cases

## Purpose

Define the gate tests that must pass before each phase is considered complete.

## Phase 0 acceptance

- schema validator passes all valid fixtures and fails all invalid fixtures
- naming validator fails known-bad id variants
- lifecycle CLI stub produces deterministic plan/apply/validate JSON outputs
- example project scaffold matches project/local-state spec

## Phase 1 destructive tests

- fresh install interrupted after config creation but before managed workflow install
- cutover interrupted after `.audiagentic/` creation but before legacy cleanup
- uninstall interrupted after runtime cleanup but before config removal
- mixed-or-invalid detection blocks apply and provides remediation text

## Phase 2 destructive and concurrency tests

- two sync attempts; second receives lock error
- repeated sync with same fragments is byte-identical
- finalize interrupted after historical append; rerun does not duplicate append
- duplicate event-id with different payload fails deterministically
- stale lock is detected and handled per lock timeout rules

## Phase 3 tests

- `lite`, `standard`, and `strict` profiles validate
- packet runner persists stage outputs and job transitions
- approval expiry moves job to timeout/cancel path per contract

## Phase 4 tests

- provider registry rejects unknown ids and invalid descriptors
- unhealthy provider blocks job selection per provider selection rules
- optional server seam can be absent with no import failures

## Phase 5 tests

- Discord disabled path leaves all prior phases functional
- Discord approval action resolves through approval core only
- migration examples cover migrated, copied-for-review, skipped-ambiguous, skipped-conflict
