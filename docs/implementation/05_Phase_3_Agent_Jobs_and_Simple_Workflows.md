# Phase 3 — Agent Jobs and Simple Workflows

## Purpose

Add a minimal job runner that sits on top of the release core rather than embedding release behavior directly.

## Scope

- job record persistence
- job state transitions
- workflow profiles
- packet runner
- stage execution contract
- approvals through approval core
- change event emission through release scripts

## Simplicity rule

MVP jobs must be small and linear.
Do not implement arbitrary workflow graphs in this phase.

## Implementation order

1. PKT-JOB-001 — job record store and state machine
2. PKT-JOB-002 — workflow profile loader and validator
3. PKT-JOB-003 — packet runner
4. PKT-JOB-004 — stage execution contract and stage output persistence
5. PKT-JOB-005 — approvals and timeouts inside jobs
6. PKT-JOB-006 — release script integration from jobs
7. PKT-JOB-011 — job control and running-job cancellation

## Exit gate

- jobs can run `lite` end to end without providers
- profile overrides validate
- jobs do not write tracked docs directly except through owned release scripts
- job cancellation remains a follow-on control path rather than a core workflow rewrite
- job-control implementation can be reviewed independently from the core job lifecycle packets
