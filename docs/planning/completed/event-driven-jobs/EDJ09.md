---
id: EDJ09
order: 110
plan: event-driven-jobs
state: completed
validate-first: true
priority: P2
work: S
---

# Document event-driven job doctrine and examples

## Description

Document the architecture, config shape, prompt injection pipeline, and operational behavior for event-driven agent jobs. Include examples for planning item creation triggering reviewer/planner profiles and explain job records vs gateway request records.

## Steps

1. Update src/audiagentic/components/agent_jobs/README.md with an 'Event-driven jobs' section documenting the IMPLEMENTED flow, naming real modules: event_triggers.py (config load/validation), event_observer.py (subscription, firing, trigger audit), foundation/templates.py + prompt context (rendering), records/jobs_store (durable job with event-source provenance), dispatch via published `agents.llm.gateway.requested`, outcomes via `agents.llm.*` lifecycle events, dead_letter.py on failures. State the async-only contract explicitly.
2. Include a worked `planning.item.created` example: the actual `.audiagentic/config/agent-jobs/event-triggers.yaml` shape, validated against the shipped event-trigger schema — copy from (or add to) an existing test fixture so the docs example is the tested example.
3. Document the correlation chain with the real key names: inbound correlation_id (or generated at firing) -> job event-source -> gateway request metadata -> lifecycle events -> job timeline (timeline.ndjson) and trigger audit (.audiagentic/runtime/agent-jobs/trigger-audit.ndjson); join keys job-id / correlation_id / trigger-id / request-id.
4. Document failure behavior and inspection points: dead-letter ndjson (dead_letter.py path), gateway rejection -> job failed, job.json + timeline.ndjson, gateway record, and the overview surfaces (agent_llm_gateway_overview now; event_jobs_overview when EDJ14 lands — mark as such if not yet shipped).
5. Cross-link OBSERVABILITY_STANDARDS' operational sidecar records section rather than restating it.

## Files

src/audiagentic/components/agent_jobs/README.md
docs/standards/OBSERVABILITY_STANDARDS.md
AGENTS.md or owning generated component config
src/audiagentic/components/agents/agents_api.py (read-only doc dependency)
src/audiagentic/components/agents/agents_gateway_events.py (read-only doc dependency)
src/audiagentic/components/agents/agents_gateway_dispatch.py (read-only doc dependency)

## Validation

Docs review; the YAML example in the README is byte-identical to (or generated from) a fixture that unit tests parse against the shipped schema; all module/file paths named in the docs exist (link-check by grep).

## Effort & Risk

Simple. Keep examples aligned with real schema names after EDJ01 lands.

## Standards

observability-standards — document timeline files, event/log roles, correlation-id propagation, and where to inspect state.
component-creation — clarify ownership split (agents own profile execution; agent-jobs own durable work).

## Notes

Clarify that agents own profile execution, agent-jobs own durable work; gateway access is events-only (compatible with the EDJ13 shared-service future). Grounded against implemented modules per RV253 — if EDJ08/EDJ14/EDJ15 land first, include their surfaces (cancel propagation, event_jobs_overview, filters) in the same pass.
DOCUMENT IMPLEMENTED REALITY, not the original item specs — known deviations to state correctly: gateway dispatch `source` is `event-trigger:<trigger-id>` (not `event:<event_type>`); trigger-audit records use `status` fired/suppressed/failed (not `outcome`); outcome-to-job matching is via metadata job-id only (the artifact-request-id fallback was not implemented — an accepted deviation; note it as such); dead-letter records carry payload_summary/metadata per dead_letter.py's required-keys set. After EDJ25, direct and event launches share one context/render pipeline — document one pipeline, not two.

## Ledger Events

- chg_20260712_055149_the-agent-jobs-readme-now-docu_9600
