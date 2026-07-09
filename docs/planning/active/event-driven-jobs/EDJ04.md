---
id: EDJ04
order: 70
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: complex
---

# Dispatch event-triggered jobs through the LLM gateway

## Description

After creating an event-triggered job record, dispatch the rendered instructions to the agents LLM gateway by publishing an `agents.llm.gateway.requested` event (the gateway already subscribes to and normalizes this topic in agents_gateway_events). Do NOT import agents_gateway_api into agent-jobs directly — publishing the event preserves component decoupling and matches the ownership-split doctrine (agents own gateway request records/execution; agent-jobs own durable work). The job should retain the resulting gateway request id and the gateway should retain correlation/subject metadata.

## Steps

1. Render prompt via the generic prompt assembly path (EDJ06/EDJ10/EDJ11), with event payload and trigger data as optional context sources.
2. Transition the job `ready -> running` at dispatch time so all gateway outcomes (including rejection) land from a `running` state — the job workflow has no `ready -> failed` edge, so outcomes must arrive after the job is running (see EDJ05).
3. Validate the exact `agents.llm.gateway.requested` payload contract against the read-only subscriber in `components/agents/agents_gateway_events.py` before publishing (required keys, optional keys, kebab vs snake case).
4. Publish `agents.llm.gateway.requested` (topic constant `_REQUESTED_TOPIC` in agents_gateway_events) with the subscriber-compatible payload, expected fields:
   - `prompt-body` (string, rendered instructions)
   - `agent-profile-id` (string, optional; from trigger, else default)
   - `blocking` (bool; false for async default, true only if trigger mode=blocking)
   - `source` (string, `event:<event_type>`)
   - `metadata` ({`job-id`, `trigger-id`, `correlation_id`, `subject`}) so lifecycle events can be matched back to the job in EDJ05
   - `context` is NOT sent unless explicitly needed; gateway receives rendered `prompt-body` plus minimal metadata
5. Define delivery semantics explicitly: event publish is fire-and-forget/async unless existing event bus contract requires sync; dispatch returns before gateway completion.
6. If event publication fails before acceptance, leave job `ready` for retry or mark dispatch-failed according to the existing workflow edge; document and test the chosen behavior.
7. Recover the gateway request id from async lifecycle events in EDJ05; EDJ04 only ensures `metadata.job-id` is present for correlation.
8. Emit agent-jobs lifecycle events for dispatch accepted/rejected.
9. Enforce architecture boundary with an import-graph/import-linter style test (or equivalent source scan) proving agent-jobs does not import `agents_gateway_api`/submit helpers.

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/components/agents/agents_gateway_events.py (read-only dependency)
src/audiagentic/components/agents/agents_gateway_queue.py (read-only dependency)

## Validation

Tests with the event bus (published event captured): assert topic=`agents.llm.gateway.requested`, payload keys match `agents_gateway_events.py` subscriber contract, rendered prompt-body, agent-profile-id, blocking flag from trigger mode, source `event:<type>`, and metadata.job-id/trigger-id/correlation_id/subject present. Assert publish failure behavior. Assert gateway lifecycle events include request-id in payload and preserve metadata.job-id so EDJ05 can correlate. Assert job transitioned ready->running on dispatch. Assert NO direct call/import of submit_llm_request or agents_gateway_api from agent-jobs using explicit architecture-boundary check.

## Effort & Risk

Complex. Because dispatch is fire-and-forget via event, there is no synchronous submit return value — the gateway request id must be recovered from the async lifecycle events (EDJ05). Define clear behavior if the gateway rejects the profile/provider config (agents.llm.rejected -> job failed).

## Standards

arch-standards — component layering (no cross-component API import; dispatch via event bus), config-over-code, AudiaGenticError at boundary.
component-creation — agents own gateway execution; agent-jobs own durable work.
observability-standards — lifecycle events carry job-id/correlation_id.

## Notes

Use the gateway request event for profile execution; do not duplicate provider dispatch or import agents' API surface into agent-jobs. Cross-check event contract against agents_gateway_events._REQUESTED_TOPIC and lifecycle payload shape in agents_gateway_queue.
