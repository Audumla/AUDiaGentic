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

1. Subscribe agent-jobs to `agents.llm.completed`, `agents.llm.failed`, `agents.llm.rejected`, `agents.llm.cancelled`.
2. Match each event to its job via `metadata.job-id` (the gateway echoes submit metadata on every lifecycle event) — primary; fallback via the stored `gateway-request` artifact request-id.
3. Capture the gateway `request-id` from the FIRST lifecycle event seen for a job (if not already persisted by EDJ04) — this closes the async request-id loop.
4. Apply explicit transitions (jobs are `running` at dispatch per EDJ04):
   - `agents.llm.completed`  -> `running -> completed`
   - `agents.llm.failed`     -> `running -> failed`
   - `agents.llm.rejected`   -> `running -> failed` (profile/provider rejected; no output)
   - `agents.llm.cancelled`  -> `running -> cancelled`
5. Persist the outcome summary, not just the state: terminal lifecycle events already carry `provider-id`, `model-id`, `error`, `attempt_count` (agents_gateway_queue._publish_lifecycle_event). Store these in the job's gateway-request artifact / timeline attributes so operators diagnose without opening the gateway record. Never copy raw output/prompts into the job record (redaction — arch-standards §8).
6. `awaiting-approval` branch: an outcome arriving in `awaiting-approval` is out-of-band — log + timeline entry, do NOT force a transition (approval flow owns that state).
7. Idempotency: job already terminal or missing -> ignore without error (dedupe duplicate/late events).
8. Timeline entries for `gateway-outcome-received` and `job-state-propagated` via the shared observability helper; include correlation_id and request-id attributes.

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/components/agent_jobs/state_machine.py
src/audiagentic/components/agent_jobs/jobs_store.py
src/audiagentic/components/agent_jobs/events.py
src/audiagentic/foundation/observability.py (read-only dependency)

## Validation

Tests: completed->completed; failed->failed; rejected->failed; cancelled->cancelled; duplicate terminal event ignored (no exception, no extra timeline entry); unknown job-id ignored; outcome during awaiting-approval logs but does not transition; outcome summary (provider-id/model-id/error/attempt_count) persisted; request-id captured from first lifecycle event when EDJ04 has not stored it; no raw prompt/output in job record. Match by metadata.job-id and artifact fallback both covered.

## Effort & Risk

Complex. This is where state propagation belongs; avoid using generic propagation engine until job/gateway relationships are modeled enough to benefit.

## Standards

arch-standards — state transitions via foundation.workflow primitives (no ad hoc state mutation), AudiaGenticError at boundary, idempotent handlers.
observability-standards — timeline entries for outcome-received and state-propagated.
component-creation — job state owned by agent-jobs; consumes agents lifecycle events read-only.

## Notes

Explicit handling first; propagation-engine adoption is EDJ08's decision. This subscriber follows the same isolation rule as EDJ02: never raise out of the bus handler; unmatchable or unprocessable events go to the EDJ12 dead-letter with correlation context.

## Ledger Events


