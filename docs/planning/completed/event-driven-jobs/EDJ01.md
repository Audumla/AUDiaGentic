---
id: EDJ01
order: 10
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P1
complexity: mid
---

# Add event-trigger configuration for agent jobs

## Description

Define project-scoped configuration for mapping event bus topics to agent job launches. Each trigger should declare an event pattern, enabled flag, agent-profile-id, dispatch mode, prompt source, prompt context inputs, target/workflow defaults, and metadata propagation policy.

## Steps

1. Add `.audiagentic/config/agent-jobs/event-triggers.yaml` loader and `event-trigger.schema.json` (draft 2020-12, additionalProperties:false).
2. Define trigger fields explicitly:
   - `contract-version` (const "v1", required)
   - `trigger-id` (string, required, unique per file)
   - `kind` (enum, v1 allows only "event"; required, no default). Discriminator gives additive headroom for future trigger kinds (schedule, webhook, file-watch — see EDJ15) without schema breakage. Do NOT implement other kinds now.
   - `enabled` (bool, default true)
   - `event-pattern` (string, required for kind=event; uses foundation.event.patterns.pattern_matches vocabulary: exact `planning.item.created`, `*` = exactly one segment, `**` = zero or more segments — do not implement a second pattern matcher)
   - `agent-profile-id` (string, optional; unset -> default agent profile at dispatch)
   - `workflow-profile` (enum lite|standard|strict, optional)
   - `target` (object, optional; kind/packet-id/job-id/artifact-path/adhoc-id mirroring job-record launch-target)
   - `prompt-template` (string) XOR `prompt-template-file` (string) — exactly one required; mutual-exclusion enforcement owned by EDJ11 but declared in this schema
   - `metadata-propagation` (object, optional; which inbound metadata keys copy forward; default propagates `correlation_id` and `subject`)
   NOTE: there is NO `mode` field. Event-triggered dispatch is async-only in v1: a bus subscriber must never block on LLM completion, and blocking-wait semantics do not survive the gateway becoming a shared multi-instance service (EDJ13). Do not add a blocking option.
3. Reject unknown fields and missing required fields with AudiaGenticError (kind `agent-jobs`). Register every new error code in the agent-jobs `error-resolutions.yaml` BEFORE first use (arch-standards §8 — unregistered codes are defects). Suggested codes: VAL-AJT-001 invalid trigger config, VAL-AJT-002 duplicate trigger-id, VAL-AJT-003 template XOR violation.
4. Provide test fixtures: exact `planning.item.created` trigger, `planning.item.*` single-segment wildcard, and `planning.**` multi-segment wildcard.

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/contracts/event-trigger.schema.json
src/audiagentic/foundation/contracts/schema_registry.py
src/audiagentic/foundation/contracts/canonical_ids.py
src/audiagentic/config/components/agent-jobs.yaml
src/audiagentic/foundation/event/event_bus.py (read-only dependency)

## Validation

Unit tests: valid single/multiple triggers; missing trigger-id/event-pattern/kind -> AudiaGenticError with registered code; unknown field rejected; enabled:false skipped by loader; exact vs `*` vs `**` patterns delegate to foundation pattern_matches; both/neither of prompt-template/prompt-template-file -> validation error; a `mode` field in config is rejected as unknown; every raised code has an error-resolutions.yaml entry (assert via get_error_resolution).

## Effort & Risk

Medium. Keep trigger semantics in agent-jobs and avoid putting job-specific behavior into foundation/event.

## Standards

arch-standards — config-over-code (trigger semantics in YAML, not Python), AudiaGenticError at public boundary, no raw ValueError.
component-creation — config lives under .audiagentic/config/agent-jobs; schema under components/agent_jobs/contracts.

## Notes

Trigger config uses the existing event bus pattern vocabulary and preserves correlation_id/subject metadata. `kind` is the only forward-compat hook — deliberately minimal; payload filters and non-event kinds are EDJ15's design call, not v1 scope.
GATED BY EDJ19 (RV231): do not add the schema until the ownership rule is codified. Default expectation: event-trigger.schema.json is component-only (under components/agent_jobs/contracts/), NOT mirrored into foundation/contracts/schemas/ and NOT registered in schema_registry/canonical_ids — drop those foundation edits from this item's files unless EDJ19 decides otherwise.

## Ledger Events


