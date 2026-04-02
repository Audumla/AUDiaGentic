# PKT-JOB-011 — Job control and running-job cancellation

**Phase:** Phase 3.4
**Status:** READY_FOR_REVIEW
**Owner:** Codex

## Objective

Add a dedicated control path so a launched job can be cancelled or stopped while pending,
awaiting approval, or actively running.

## Prerequisites

- PKT-JOB-001 is verified
- PKT-JOB-004 is verified
- PKT-JOB-005 is verified
- PKT-JOB-009 is verified

## Implementation steps

1. define the job-control runtime record and event shape
2. add cooperative stop checks to the packet runner
3. extend the state machine with legal cancellation transitions from running stages
4. add a CLI or service surface for cancel/stop requests
5. add tests for pre-run, awaiting-approval, and running cancellation paths

## Core logic pseudocode

```python
def request_job_control(project_root, job_id, action, reason, requested_by):
    write_control_record(...)
    if action in {"cancel", "stop"}:
        signal_runner_stop(...)
    if action == "kill":
        hard_stop_if_supported(...)
    persist_control_outcome(...)
```

## Files to create/update

- `docs/specifications/architecture/32_DRAFT_Job_Control_and_Running_Job_Cancellation.md`
- `src/audiagentic/execution/jobs/state_machine.py`
- `src/audiagentic/execution/jobs/packet_runner.py`
- `src/audiagentic/execution/jobs/store.py`
- `src/audiagentic/execution/jobs/approvals.py`
- `src/audiagentic/execution/jobs/control.py` or equivalent job-control module
- job-control CLI or service surface
- job-control tests and fixtures

## Fixtures to add

- job-control request fixture
- running-job cancellation fixture
- awaiting-approval cancellation fixture
- pre-run cancellation fixture

## Tests to add

- unit test for the control record writer
- unit test for legal transition checks
- integration test for awaiting-approval cancellation
- integration test for running-job cancellation
- integration test for stage-output preservation after cancellation

## Acceptance criteria

- a user can request cancellation of a running job
- the job record, control record, and event log all reflect the stop request
- stage outputs already written remain available for inspection
- the final terminal state is deterministic and testable
- the control path does not change prompt-launch or provider execution semantics

## Recovery procedure

- delete the generated job-control record for the test job
- remove any partial control events for the sandbox job
- reset the job record to the last verified state if the test failed mid-transition
- keep existing stage outputs unless the test explicitly verified cleanup behavior

## Likely files or surfaces

- `src/audiagentic/execution/jobs/control.py`
- `src/audiagentic/execution/jobs/state_machine.py`
- `src/audiagentic/execution/jobs/packet_runner.py`
- `src/audiagentic/execution/jobs/store.py`
- `src/audiagentic/execution/jobs/approvals.py`
- `src/audiagentic/channels/cli/main.py`
- job-control CLI or service surface
- job-control tests

## Rollback guidance

- remove the job-control surface and stop checks first
- leave the base job state machine and launch contracts intact
