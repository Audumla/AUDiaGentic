# Draft Job Control and Running Job Cancellation

Status: draft
Phase: 3.4
Feature slot: .4

## Purpose

Define a dedicated job-control surface so launched jobs can be stopped or cancelled after they
have been created, including while a job is actively running.

## Problem statement

The current job engine can reach `cancelled` through approval flow and other pre-run paths, but
it does not yet define a user-facing control path for cancelling a running job.

That leaves two gaps:
- there is no explicit “kill this job” contract for active work
- there is no stable runtime artifact for recording the cancellation request and its outcome

## Goals

- provide a user-facing job control action for cancel/stop
- make the control action deterministic and observable
- preserve the existing job state machine as the source of truth
- keep the cancellation path separate from approvals and reviews

## Normative rules

- job cancellation must be explicit and project-local
- a running job may be cancelled only through the new job-control path
- the control path must preserve provenance and record who requested the stop
- the control path must not silently drop in-progress artifacts
- the state machine must remain the single source of truth for the final terminal state

## Control model

### Soft cancel

Soft cancel requests a job to stop at the next safe boundary and transition to `cancelled`
when the runner acknowledges the request.

### Hard stop

Hard stop asks the active runner or provider adapter to terminate immediately if supported,
then persist the final control outcome and terminal state.

### Cooperative stop

The runner checks for stop requests between stages and before handing off to provider work.
This is the default first implementation path.

## Required runtime artifacts

Suggested control artifacts:
- `.audiagentic/runtime/jobs/<job-id>/job-control.json`
- `.audiagentic/runtime/jobs/<job-id>/control-events.ndjson`

The exact naming may change, but the project must retain a stable per-job control record.

## Required data

Each control request should capture:
- `job-id`
- `project-id`
- `requested-action` (`cancel`, `stop`, or `kill`)
- `requested-by`
- `requested-at`
- `reason`
- `result`
- `applied-at`

## State management

The control path must integrate with the existing state machine.
At minimum, the following transitions or controls must be defined:
- `running` -> `cancelled` when a stop request is honored
- `awaiting-approval` -> `cancelled` when a stop request is honored
- `ready` -> `cancelled` for pre-run cancellation

If a hard-stop cannot be cleanly acknowledged, the job must still end in a deterministic
terminal state and the failure reason must be recorded.

## Monitoring expectations

Cancellation must be visible through:
- the job record state
- the control record
- stage outputs written before the stop
- event log entries for the request and outcome

## Non-goals

- arbitrary pause/resume semantics
- multi-job orchestration
- changing provider prompt-trigger behavior
- changing review bundle semantics

