---
id: EDJ09
order: 110
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P2
complexity: simple
---

# Document event-driven job doctrine and examples

## Description

Document the architecture, config shape, prompt injection pipeline, and operational behavior for event-driven agent jobs. Include examples for planning item creation triggering reviewer/planner profiles and explain job records vs gateway request records.

## Steps

1. Update agent-jobs README with the event trigger flow, including the async-only dispatch contract (publish `agents.llm.gateway.requested`, outcomes via `agents.llm.*` lifecycle events — no blocking mode for triggers).
2. Add example `planning.item.created` trigger config (must parse against the real EDJ01 schema).
3. Document the correlation chain end-to-end: inbound event correlation_id (or generated at firing) -> job record event-source -> gateway request metadata -> lifecycle events -> job + gateway timelines; list the join keys (job-id, correlation_id, trigger-id, request-id).
4. Document failure behavior: dispatch/handler failures dead-letter (EDJ12), gateway rejection -> job failed, and where to inspect state (job.json, timeline.ndjson, gateway record, trigger audit/overview from EDJ14).

## Files

src/audiagentic/components/agent_jobs/README.md
docs/standards/OBSERVABILITY_STANDARDS.md
AGENTS.md or owning generated component config
src/audiagentic/components/agents/agents_api.py (read-only doc dependency)
src/audiagentic/components/agents/agents_gateway_events.py (read-only doc dependency)
src/audiagentic/components/agents/agents_gateway_dispatch.py (read-only doc dependency)

## Validation

Docs review plus sample config parsed by unit test fixture. Verify README examples match real schema names after EDJ01/EDJ10/EDJ11 land, diagnostics paths exist or are marked conditional, and AGENTS.md update happens through the managed source if applicable.

## Effort & Risk

Simple. Keep examples aligned with real schema names after EDJ01 lands.

## Standards

observability-standards — document timeline files, event/log roles, correlation-id propagation, and where to inspect state.
component-creation — clarify ownership split (agents own profile execution; agent-jobs own durable work).

## Notes

Clarify that agents own profile execution, agent-jobs own durable work; the gateway is accessed only via events, which is what keeps the design compatible with a future shared gateway service (EDJ13). Keep examples aligned with real schema names after EDJ01 lands.

## Ledger Events


