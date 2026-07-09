---
id: EDJ02
order: 40
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: mid
---

# Subscribe agent-jobs to configured event triggers

## Description

Add an agent-jobs event observer that subscribes to configured event patterns and dispatches matching events to the trigger handler. The observer should be component-owned and registered through the component descriptor lifecycle observer mechanism.

## Steps

1. Add `agent_jobs/event_observer.py` with idempotent registration.
2. Update `src/audiagentic/config/components/agent-jobs.yaml` to register the observer class through the component lifecycle observer mechanism.
3. Load trigger config at registration time and subscribe to enabled patterns.
4. Track subscription handles and clean up stale subscriptions on re-registration/reload using event bus unsubscribe support.
5. On event, map the real `EventEnvelope` dict shape into event_type, payload, metadata, and trigger config for the dispatcher; verify against `components/planning/events.py` output.
6. Preserve event bus subscriber isolation; handler failures should log via structured event logging/observability and publish/record `agent.job.trigger.rejected` (or final chosen topic) without breaking other subscribers.
7. Record whether rejection is job timeline state (EDJ03/EDJ07) or observer-only log when no job record exists yet.

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/config/components/agent-jobs.yaml

## Validation

Unit tests for idempotent registration (second register does not double subscriptions), subscription count, stale subscription cleanup on reload, disabled trigger skip, malformed payload handling, planning.item.created envelope mapping, and handler failure isolation with rejected outcome/log emitted.

## Effort & Risk

Medium. Avoid import-time side effects beyond established observer subscription pattern.

## Standards

arch-standards — no import-time side effects beyond the established observer subscription pattern; AudiaGenticError at boundary; subscriber isolation (handler failure must not break other subscribers).
component-creation — observer registered through the component descriptor lifecycle-observer mechanism.

## Notes

Use `metadata.correlation_id` and `metadata.subject` from the inbound event as execution lineage.
