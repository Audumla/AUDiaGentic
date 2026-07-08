---
id: EDJ05
order: 80
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: complex
---

# Propagate gateway outcomes back to job state

## Description

Use gateway lifecycle events to update the owning event-triggered job. A completed gateway request should mark the job completed; failed/rejected/cancelled should mark the job failed or cancelled according to workflow rules.

## Steps

1. Subscribe agent-jobs to `agents.llm.completed`, `agents.llm.failed`, `agents.llm.rejected`, and `agents.llm.cancelled`.
2. Match events to jobs via metadata job id or stored gateway request id.
3. Use existing agent_jobs state machine transitions to update job state.
4. Record timeline events for gateway outcome received and job state propagated.
5. Handle missing/terminal jobs idempotently.

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/components/agent_jobs/state_machine.py
src/audiagentic/components/agent_jobs/jobs_store.py

## Validation

Tests for completed -> job completed, failed/rejected -> job failed, cancelled -> job cancelled, duplicate terminal events ignored.

## Effort & Risk

Complex. This is where state propagation belongs; avoid using generic propagation engine until job/gateway relationships are modeled enough to benefit.

## Standards



## Notes

May later use foundation propagation engine for job/stage/request relationships, but direct explicit handling is safer first.
