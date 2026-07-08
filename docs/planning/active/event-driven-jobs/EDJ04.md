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

1. Render prompt template from event payload, metadata, trigger, and job context.
2. Publish `agents.llm.gateway.requested` with mode async by default (do not call submit_llm_request directly from agent-jobs).
3. Pass source `event:<event_type>` plus trigger id/job id/agent-profile-id in payload+metadata.
4. Correlate the resulting gateway request id back to the job (via metadata job id echoed on the gateway lifecycle events, per EDJ05) and persist it in job artifact or trigger result metadata.
5. Emit agent-jobs lifecycle events for dispatch accepted/rejected.

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agents/agents_gateway_events.py

## Validation

Tests with monkeypatched gateway submit verifying profile id, prompt body, source, metadata, job id, and correlation id.

## Effort & Risk

Complex. Because dispatch is fire-and-forget via event, there is no synchronous submit return value — the gateway request id must be recovered from the async lifecycle events (EDJ05). Define clear behavior if the gateway rejects the profile/provider config (agents.llm.rejected -> job failed).

## Standards



## Notes

Use the gateway request event for profile execution; do not duplicate provider dispatch or import agents' API surface into agent-jobs. Cross-check event contract against agents_gateway_events._REQUESTED_TOPIC.
