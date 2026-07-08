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

Document the architecture, config shape, and operational behavior for event-driven agent jobs. Include examples for planning item creation triggering reviewer/planner profiles and explain job records vs gateway request records.

## Steps

1. Update agent-jobs README with event trigger flow.
2. Add example `planning.item.created` trigger config.
3. Explain correlation id propagation and timeline files.
4. Document failure/retry behavior and where to inspect state.

## Files

src/audiagentic/components/agent_jobs/README.md
docs/standards/OBSERVABILITY_STANDARDS.md

## Validation

Docs review plus sample config parsed by unit test fixture.

## Effort & Risk

Simple. Keep examples aligned with real schema names after EDJ01 lands.

## Standards



## Notes

Clarify that agents own profile execution, agent-jobs own durable work.
