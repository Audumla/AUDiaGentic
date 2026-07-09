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

Define project-scoped configuration for mapping event bus topics to agent job launches. Each trigger should declare an event pattern, enabled flag, agent-profile-id, dispatch mode, prompt source, prompt context inputs, target/workflow defaults, and metadata propagation policy.

## Steps

1. Add `.audiagentic/config/agent-jobs/event-triggers.yaml` loader and `event-trigger.schema.json` (draft 2020-12, additionalProperties:false).
2. Register event-trigger schema with `foundation/contracts/schema_registry.py` using canonical IDs from `foundation/contracts/canonical_ids.py`, or document why runtime validation uses a component-local schema path.
3. Update `src/audiagentic/config/components/agent-jobs.yaml` so the component lifecycle loads the event trigger module/config surface.
4. Define trigger fields explicitly:
   - `contract-version` (const "v1", required)
   - `trigger-id` (string, required, unique per file)
   - `enabled` (bool, default true)
   - `event-pattern` (string, required; exact e.g. `planning.item.created` or trailing wildcard `planning.item.*` using `foundation/event/event_bus.py` accepted syntax)
   - `agent-profile-id` (string, optional; unset -> default agent profile at dispatch)
   - `mode` (enum async|blocking, default async)
   - `workflow-profile` (enum lite|standard|strict, optional)
   - `target` (object, optional; kind/packet-id/job-id/artifact-path/adhoc-id mirroring job-record launch-target)
   - `prompt-template` (string) XOR `prompt-template-file` (string) — exactly one required; mutual-exclusion enforcement owned by EDJ11 but declared in this schema
   - `context` (object, optional; opaque key-value data merged into `AgentJobPromptContext.launch.input`, rendered by EDJ10/EDJ06; document supported depth/size limits, no nested event dispatch)
   - `metadata-propagation` (object, optional; policy for which inbound metadata keys copy forward; default propagates `correlation_id` and `subject`)
5. Route prompt source and context fields through the generic prompt assembly layer from EDJ10/EDJ11. Event trigger config must not render prompts itself.
6. Reject unknown fields and missing required fields with AudiaGenticError (VAL-* code, kind `agent-jobs`).
7. Provide a sample `planning.item.created` trigger and a wildcard `planning.item.*` trigger as test fixtures.

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/contracts/event-trigger.schema.json
src/audiagentic/foundation/contracts/schema_registry.py
src/audiagentic/foundation/contracts/canonical_ids.py
src/audiagentic/config/components/agent-jobs.yaml
src/audiagentic/foundation/event/event_bus.py (read-only dependency)

## Validation

Unit tests: valid single/multiple triggers; missing `trigger-id`/`event-pattern` -> AudiaGenticError; unknown field rejected; `enabled:false` skipped by loader; exact vs wildcard pattern parsing follows event bus syntax; schema registry validation succeeds; component descriptor loads trigger module/config; both/neither of prompt-template/prompt-template-file -> validation error; default `mode`/`enabled`/metadata-propagation applied; `context` preserved for EDJ10 without rendering at load time and respects documented depth/size constraints.

## Effort & Risk

Medium. Keep trigger semantics in agent-jobs and avoid putting job-specific behavior into foundation/event.

## Standards

arch-standards — config-over-code (trigger semantics in YAML, not Python), AudiaGenticError at public boundary, no raw ValueError.
component-creation — config lives under .audiagentic/config/agent-jobs; schema under components/agent_jobs/contracts.

## Notes

Trigger config should use existing event bus pattern vocabulary and preserve correlation_id/subject metadata. Prompt context/rendering is shared job-launch pipeline behavior, not event-trigger-only behavior. Ledger/release tracking is not part of event-trigger runtime state; event-driven jobs are a separate operational surface.
