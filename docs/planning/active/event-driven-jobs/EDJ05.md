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

1. Subscribe agent-jobs to `agents.llm.completed`, `agents.llm.failed`, `agents.llm.rejected`, `agents.llm.cancelled`, plus informational `agents.llm.queued` and `agents.llm.started` for timeline milestones.
2. Match each terminal event to its job via `metadata.job-id` (primary) or the stored `gateway-request` artifact request-id (fallback).
3. Add/confirm `jobs_store.py` lookup helpers (`find_by_job_id` and request-id fallback) rather than scanning ad hoc in handlers unless current store API already provides them.
4. Apply explicit, named transitions through `state_machine.transition_and_persist()`/foundation workflow primitives; do not mutate job state directly. Jobs are already `running` at dispatch (EDJ04):
   - `agents.llm.completed`  -> `running -> completed`
   - `agents.llm.failed`     -> `running -> failed`
   - `agents.llm.rejected`   -> `running -> failed` (profile/provider rejected; job never produced output)
   - `agents.llm.cancelled`  -> `running -> cancelled`
5. `awaiting-approval` branch: a gateway outcome arriving while the job is in `awaiting-approval` is out-of-band — log and record a timeline entry, do NOT force a transition (approval flow owns that state).
6. Idempotency: if the job is already terminal (`completed`/`failed`/`cancelled`) or missing, ignore the event without error (dedupe duplicate/late lifecycle events).
7. Record `queued`, `started`, `gateway-outcome-received`, `gateway-linked`, and `job-state-propagated` timeline events via EDJ07 helpers and `foundation.observability.record_timeline_event()`.
8. Append the `gateway-request` artifact when lifecycle payload provides request-id and correlation succeeds.
9. Guard concurrent outcome races for the same job with existing store/state locking or add a per-job lock around load-transition-persist.

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/components/agent_jobs/state_machine.py
src/audiagentic/components/agent_jobs/jobs_store.py
src/audiagentic/components/agent_jobs/events.py
src/audiagentic/foundation/observability.py (read-only dependency)

## Validation

Tests: queued/started append timeline milestones; completed->job completed; failed->job failed; rejected->job failed; cancelled->job cancelled; duplicate terminal event ignored (no exception, no extra terminal transition); event for unknown job-id ignored; outcome while awaiting-approval logs but does not transition. Match by metadata.job-id and by gateway-request artifact fallback both covered. Concurrent completed+failed for one job results in one terminal transition and deterministic ignored-late event behavior.

## Effort & Risk

Complex. This is where state propagation belongs; avoid using generic propagation engine until job/gateway relationships are modeled enough to benefit.

## Standards

arch-standards — state transitions via foundation.workflow primitives (no ad hoc state mutation), AudiaGenticError at boundary, idempotent handlers.
observability-standards — timeline entries for outcome-received and state-propagated.
component-creation — job state owned by agent-jobs; consumes agents lifecycle events read-only.

## Notes

May later use foundation propagation engine for job/stage/request relationships, but direct explicit handling is safer first.
