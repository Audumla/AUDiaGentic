---
id: EDJ01
order: 10
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: mid
---

# Add event-trigger configuration for agent jobs

## Description

Define project-scoped configuration for mapping event bus topics to agent job launches. Each trigger should declare an event pattern, enabled flag, agent-profile-id, dispatch mode, prompt template, target/workflow defaults, and metadata propagation policy.

## Steps

1. Add `.audiagentic/config/agent-jobs/event-triggers.yaml` loader and schema.
2. Support trigger ids, enabled flags, exact/wildcard event patterns, agent-profile-id, mode, workflow-profile, target, and prompt-template.
3. Validate unknown fields and missing required fields with AudiaGenticError.
4. Document sample trigger for `planning.item.created`.

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/contracts/event-trigger.schema.json

## Validation

Unit tests for config loading, validation errors, disabled triggers, and wildcard event pattern handling.

## Effort & Risk

Medium. Keep trigger semantics in agent-jobs and avoid putting job-specific behavior into foundation/event.

## Standards



## Notes

Trigger config should use existing event bus pattern vocabulary and preserve correlation_id/subject metadata.
