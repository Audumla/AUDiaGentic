---
id: EDJ04
order: 70
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P1
complexity: complex
---

# Dispatch event-triggered jobs through the LLM gateway

## Description

After creating an event-triggered job record, dispatch the rendered instructions to the agents LLM gateway by publishing an `agents.llm.gateway.requested` event (the gateway already subscribes to and normalizes this topic in agents_gateway_events). Do NOT import agents_gateway_api into agent-jobs directly — publishing the event preserves component decoupling and matches the ownership-split doctrine (agents own gateway request records/execution; agent-jobs own durable work). The job should retain the resulting gateway request id and the gateway should retain correlation/subject metadata.

## Steps

1. Render prompt template from event payload, metadata, trigger, and job context (EDJ06/EDJ10).
2. Transition the job `ready -> running` at dispatch time so all gateway outcomes (including rejection) land from a `running` state — the job workflow has no `ready -> failed` edge (see EDJ05).
3. Publish `agents.llm.gateway.requested` (topic constant `_REQUESTED_TOPIC` in agents_gateway_events) with payload:
   - `prompt-body` (string, rendered instructions)
   - `agent-profile-id` (string, optional; from trigger, else default)
   - `blocking`: ALWAYS false. Event-triggered dispatch is async-only (no `mode` in trigger config — EDJ01); blocking waits do not survive the gateway becoming a shared service (EDJ13).
   - `source` (string, `event:<event_type>`)
   - `metadata` ({`job-id`, `trigger-id`, `correlation_id`, `subject`}) — the gateway echoes record metadata on every lifecycle event (see agents_gateway_queue._publish_lifecycle_event), so this is the correlation channel back to the job in EDJ05.
4. Recover the gateway `request-id` from the lifecycle events (all of them carry it in the payload) and persist it as the job's `gateway-request` artifact (EDJ03). There is no synchronous return value on the event path.
5. Emit agent-jobs lifecycle events for dispatch accepted/rejected. Register any new dispatch error codes in agent-jobs error-resolutions.yaml before use (arch-standards §8); dispatch publish failure follows the EDJ02 dead-letter path (format owned by EDJ12).

Review gate before EDJ05: agent-jobs does NOT import agents_gateway_api; dispatch goes only through the published event with blocking=false; job is `running` before outcomes; metadata carries job-id+correlation_id.

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/components/agents/agents_gateway_events.py (read-only dependency)
src/audiagentic/components/agents/agents_gateway_queue.py (read-only dependency)

## Validation

Tests with the event bus (published event captured): topic=`agents.llm.gateway.requested`; prompt-body; agent-profile-id; blocking is false; source `event:<type>`; metadata.job-id/trigger-id/correlation_id present. Job transitioned ready->running on dispatch. Architecture-boundary test: no import of agents_gateway_api from agent_jobs modules. New error codes have error-resolutions.yaml entries.

## Effort & Risk

Complex. Because dispatch is fire-and-forget via event, there is no synchronous submit return value — the gateway request id must be recovered from the async lifecycle events (EDJ05). Define clear behavior if the gateway rejects the profile/provider config (agents.llm.rejected -> job failed).

## Standards

arch-standards — component layering (no cross-component API import; dispatch via event bus), config-over-code, AudiaGenticError at boundary.
component-creation — agents own gateway execution; agent-jobs own durable work.
observability-standards — lifecycle events carry job-id/correlation_id.

## Notes

Use the gateway request event for profile execution; do not duplicate provider dispatch or import agents' API surface into agent-jobs. The gateway is currently in-process per project; nothing in this item may assume same-process access to gateway internals (queue manager, wait) — event publish + lifecycle-event consumption is the whole contract, which is exactly what keeps this compatible with EDJ13's shared-service future.

## Ledger Events


