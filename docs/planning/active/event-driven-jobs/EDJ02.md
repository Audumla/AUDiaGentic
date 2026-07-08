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
2. Load trigger config at registration time and subscribe to enabled patterns.
3. On event, pass event_type, payload, metadata, and trigger config to dispatcher.
4. Preserve event bus subscriber isolation; handler failures should log and publish/record rejection outcomes without breaking other subscribers.

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/config/components/agent-jobs.yaml

## Validation

Unit tests for idempotent registration, subscription count, disabled trigger skip, and malformed payload handling.

## Effort & Risk

Medium. Avoid import-time side effects beyond established observer subscription pattern.

## Standards



## Notes

Use `metadata.correlation_id` and `metadata.subject` from the inbound event as execution lineage.
