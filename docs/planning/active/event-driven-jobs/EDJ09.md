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

1. Create or update `src/audiagentic/components/agent_jobs/README.md` with event trigger flow.
2. Add example `planning.item.created` trigger config.
3. Add example direct prompt launch using `prompt-template-file` and explicit `context` to show injection is not event-only.
4. Explain full agent-profile resolution chain: trigger `agent-profile-id` -> prompt/context path -> gateway request event normalization -> agents profile resolution/defaulting.
5. Explain correlation id propagation and timeline files.
6. Add diagnostics/runbook section with runtime locations for job records, per-job `timeline.ndjson`, event store (if enabled), and gateway request records, plus commands/tests operators can use to inspect state.
7. Document failure/retry behavior, provider dispatch interaction (`agents_gateway_dispatch.py`), fallback profiles if supported, and terminal vs transient error classification as seen from job timelines.
8. Document touch points: agent-jobs owns triggers/job records/prompt context; agents owns gateway execution; foundation owns renderer/observability/event bus; planning only emits planning events with creator/reviewer ids.
9. Update project `AGENTS.md` or the owning component config that generates its managed section with a brief reference/link to event-driven job doctrine, without editing generated output only.

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

Clarify that agents own profile execution, agent-jobs own durable work.
