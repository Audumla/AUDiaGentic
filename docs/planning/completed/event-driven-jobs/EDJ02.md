---
id: EDJ02
order: 40
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P1
work: M
---

# Subscribe agent-jobs to configured event triggers

## Description

Add an agent-jobs event observer that subscribes to configured event patterns and dispatches matching events to the trigger handler. The observer should be component-owned and registered through the component descriptor lifecycle observer mechanism.

## Steps

1. Add `agent_jobs/event_observer.py` with idempotent registration through the component descriptor lifecycle-observer mechanism.
2. Load trigger config at registration time and subscribe to enabled patterns via the event bus (patterns delegate to foundation.event.patterns).
3. On event, pass event_type, payload, metadata, and trigger config to the trigger handler.
4. Correlation doctrine (load-bearing for observability end-to-end):
   - if inbound `metadata.correlation_id` is present, propagate it unchanged through job record, gateway metadata, timeline entries, and lifecycle events;
   - if absent, GENERATE one at trigger-firing time (uuid) so every event-triggered job has a correlation id from its first artifact onward;
   - the new job's id becomes `metadata.subject` for events the job itself emits downstream.
5. Subscriber isolation: a handler failure must log (exc_info=True), write a durable firing-failure record (dead-letter — format owned by EDJ12), and return without raising, so other bus subscribers are unaffected.
6. Record a trigger-firing audit entry for every match: fired / suppressed(disabled) / failed (record shape and writer owned by EDJ14; consumed by EDJ14's overview).

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/config/components/agent-jobs.yaml

## Validation

Unit tests: idempotent registration (double-register subscribes once); subscription count matches enabled triggers; disabled trigger records 'suppressed' audit entry and does not dispatch; malformed payload -> handler logs + dead-letters + does not raise; inbound correlation_id propagated verbatim; missing correlation_id -> generated and stable across job record + dispatch metadata.

## Effort & Risk

Medium. Avoid import-time side effects beyond established observer subscription pattern.

## Standards

arch-standards — no import-time side effects beyond the established observer subscription pattern; AudiaGenticError at boundary; subscriber isolation (handler failure must not break other subscribers).
component-creation — observer registered through the component descriptor lifecycle-observer mechanism.

## Notes

Use `metadata.correlation_id` and `metadata.subject` from the inbound event as execution lineage. Dead-letter record format is defined by EDJ12 — this item just writes it at the failure point; if EDJ12 has not landed, write a minimal ndjson stub in the job area and note it in EDJ12.

## Ledger Events

- chg_20260710_085734_created-seven-critical-edj-rev_7918
