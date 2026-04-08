---
id: spec-0011
label: Phase 3 Jobs and Simple Workflows
state: draft
summary: Build simple job engine using release core
request_refs:
- request-0002
task_refs: []
---

# Phase 3 — Jobs and Simple Workflows

## Purpose

Build a simple job engine that uses the release core instead of reimplementing it.

## Scope

- Job records and store
- State machine
- Workflow profiles
- Packet runner
- Approval handling inside jobs
- Release bridge from jobs to scripts

## Out of scope

- provider execution
- Discord delivery
- complex orchestration

## Implementation order

1. [PKT-JOB-001](task-0067) — job records and store
2. [PKT-JOB-002](task-0068) — state machine
3. [PKT-JOB-003](task-0069) — workflow profiles
4. [PKT-JOB-004](task-0070) — packet runner
5. [PKT-JOB-005](task-0071) — approval handling
6. [PKT-JOB-006](task-0072) — release bridge
7. [PKT-JOB-007](task-0073) — job validation
8. [PKT-JOB-008](task-0074) — job monitoring
9. [PKT-JOB-009](task-0075) — job cancellation
10. [PKT-JOB-010](task-0076) — job documentation
11. [PKT-JOB-011](task-0077) — job testing

## Exit gate

- all job commands functional
- state machine correct
- workflows execute
- release bridge works

# Requirements

1. Job engine must use release core
2. State machine must be correct
3. Workflows must execute

# Constraints

- No provider execution
- No Discord delivery
- No complex orchestration

# Acceptance Criteria

1. All job commands functional
2. State machine correct
3. Workflows execute
4. Release bridge works
