---
id: EDJ08
order: 80
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P2
complexity: mid
---

# Propagate job cancellation to the owning gateway request

## Description

DECISION (recorded here, closing the original evaluation): the generic StatePropagationEngine is REJECTED for job/gateway relationships — EDJ05 landed explicit gateway->job outcome handling and it is sufficient; do not migrate it. The remaining unimplemented propagation is the reverse direction: when a job is cancelled (control.py transitions job -> cancelled), its owning gateway request keeps running/queued. Implement job-cancelled -> gateway cancel via a new gateway-subscribed event, preserving the events-only boundary (agent-jobs must not import agents_gateway_api).

## Steps

1. Agents owns the new topic literal `agents.llm.gateway.cancel-requested` in `agents_gateway_events.py`; do not export/import a topic constant across components. Add `_on_cancel_requested(event_type, payload, metadata)` beside `_on_llm_requested`, and subscribe it in that module's existing `register()` path. Required payload: `{"project-root": str, "request-id": str}`. Required metadata passthrough keys: `job-id`, `correlation_id`; no other keys are required. Invalid/missing fields: logger.warning + return; never raise.
2. Gateway handler calls only `agents_gateway_api.cancel_llm_request(Path(project_root), request_id)`. Catch `AudiaGenticError` and all external exceptions; log `exc_info=True`, then return. It does not dead-letter: it owns only gateway request cancellation; agent-jobs owns the originating control event's durable audit.
3. Add agent-jobs-local `_publish_gateway_cancel_requested(project_root, job, correlation_id)` in `control.py`. It finds exactly one artifact with `kind == "gateway-request"` and string `request-id`; if absent, no-op. Publish synchronously after—and only after—the job transition to `cancelled` has persisted. Metadata is a new dict containing `{job-id, correlation_id}`; payload is exact shape in step 1.
4. Call helper from exactly two paths: `request_job_control` after its immediate ready/awaiting-approval cancellation, and `apply_pending_job_control` after its active-state cancellation. Do not publish for terminal/ignored or still-pending control requests. Record `job.gateway-cancel-requested` only after publish succeeds. Existing gateway outcome handling remains idempotent for terminal jobs.
5. If event publish raises, write agent-jobs dead-letter with event_type `agents.llm.gateway.cancel-requested`, redacted identifier-only payload, and correlation_id; log + return. Job stays cancelled—never roll back a persisted local cancellation.
6. Add `job.gateway-cancel-requested` to EDJ07's canonical job timeline event-name tuple. No new error code unless a new `AudiaGenticError` is introduced; register any such code before use.

## Files

src/audiagentic/components/agents/agents_gateway_events.py
src/audiagentic/components/agent_jobs/control.py
src/audiagentic/components/agent_jobs/dead_letter.py (consumer)
tests/unit/agents/test_agents_gateway_events.py
tests/unit/jobs/test_control.py

## Validation

Tests: cancelling a job with a gateway-request artifact publishes cancel-requested with request-id + job-id/correlation_id; job without artifact publishes nothing; gateway handler cancels queued request (state cancelled) and flags running request; resulting agents.llm.cancelled on an already-cancelled job is ignored idempotently (no error, no duplicate timeline entry); publish failure dead-letters and does not raise; no agents_gateway_api import appears in agent_jobs (boundary re-check).

## Effort & Risk

Medium. Touches both components but each side is small and mirrors existing patterns (_on_llm_requested for the handler; EDJ04's publish pattern for the emitter). Risk: double-cancel races — covered by gateway cancel semantics and EDJ05 idempotency.

## Standards

arch-standards — events-only cross-component boundary; handlers never raise; registered error codes for any new codes.
observability-standards — timeline entry + dead-letter on failure, correlation keys throughout.

## Notes

Original item was an evaluation; RV250 recorded the decision (reject generic propagation engine — explicit handling stays) and converted the actionable remainder into this implementation. If a future need for modeled relationships emerges, raise a fresh item; do not resurrect the engine question here.

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_054320_cancelling-a-job-now-also-canc_7019
