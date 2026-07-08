---
id: EDJ10
order: 30
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: mid
---

# Add event trigger prompt context object

## Description

Build a prompt context layer for event-driven agent jobs. The context object should expose event payload, event metadata, trigger config, job/session ids, correlation id, subject, project root, and selected session data through stable replacement keys for templated prompts.

## Steps

1. FIRST verify the real emitted payload shape of `planning.item.created` (planning/events.py publishes item identity as `metadata.subject.id`; confirm whether the payload itself carries a top-level `id` before templates depend on `{payload.id}`). Adjust key mapping to match reality.
2. Define `EventJobPromptContext` shape and builder.
3. Include aliases for common keys: `payload`, `metadata`, `trigger`, `job`, `session`, `project`, `correlation_id`, `subject`.
4. Ensure planning events expose the item id under a stable key (`{plan_item.id}`), sourced from whichever of payload/subject actually carries it — do not assume `{payload.id}` without step 1 confirmation.
5. Preserve only safe/redacted fields; avoid dumping raw large records by default.
6. Add tests for context produced from `planning.item.created`, asserting the item-id key resolves against the real event payload.

## Files

src/audiagentic/components/agent_jobs/event_context.py
src/audiagentic/components/agent_jobs/event_triggers.py
tests/unit/jobs/test_event_context.py

## Validation

Unit tests for context keys, planning item id injection, metadata/correlation propagation, and missing optional session data.

## Effort & Risk

Medium. Need stable key naming before templates depend on it.

## Standards



## Notes

This is the layer prompts reference; keep rendering separate from context construction. NOTE: `planning.item.created` carries subject identity in `metadata.subject.{kind,id}` (planning/events.py) — confirm payload-level `id` existence before wiring `{payload.id}` into the flagship EDJ09 example.
