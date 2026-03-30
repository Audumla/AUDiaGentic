# Phase 3.4 — Job Control and Running Job Cancellation

Phase 3.4 adds an explicit job-control path so a launched job can be cancelled or stopped
while it is pending, awaiting approval, or actively running.

Status: ready for review
Feature slot: .4

## Scope

This phase adds:
- a job-control contract and runtime record
- cooperative running-job cancellation
- a CLI/API surface for job stop/cancel
- state machine updates needed for `running -> cancelled`
- tests for cancellation, cleanup, and monitoring visibility

This phase does not:
- redesign the core job state machine beyond the minimal control transitions
- add workflow graphs or pause/resume semantics
- change prompt launch, review, or provider execution contracts

## Recommended implementation order

1. add the job-control contract and runtime record
2. add cooperative stop checks to the runner
3. add the job cancel/stop CLI surface
4. extend the state machine with the legal cancellation transitions
5. add tests for pre-run, awaiting-approval, and running cancellation

## Completion criteria for the draft

- a running job can be stopped deterministically
- a cancellation request is visible in runtime artifacts
- the job record ends in `cancelled` when cancellation succeeds
- partial output remains on disk for postmortem visibility
- the draft can be implemented without changing provider prompt semantics

## Rollout guidance

- keep the job-control path separate from approvals
- make cancellation cooperative first, then consider hard-stop support per runner
- keep monitoring simple: job record, control record, stage outputs, event log
- do not add a new workflow model just to support job termination
