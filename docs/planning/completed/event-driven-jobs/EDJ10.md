---
id: EDJ10
order: 30
plan: event-driven-jobs
state: completed
validate-first: true
priority: P1
work: M
---

# Add generic agent job prompt context object

## Description

Build a trigger-neutral prompt context layer for agent jobs. Any launch path (event trigger, code/API request, CLI/MCP prompt launch, scheduled trigger later) should create the same `AgentJobPromptContext` shape before rendering. Event payloads are one optional context source, not the owner of injection.

## Steps

1. Define `AgentJobPromptContext` and builders under agent-jobs using an explicit type (`TypedDict` or dataclass; choose based on existing style). Inputs: `project_root`, launch source, trigger config (optional), event envelope (optional), explicit request context (optional), session data (optional), target, job id, correlation id, subject, and agent-profile id.
2. Capture a live `planning.item.created` event through `publish_planning_event()`/`EventEnvelope` in a unit test before finalizing mappings; assert the exact dict representation used by builders.
3. Include stable top-level aliases: `job`, `project`, `launch`, `trigger`, `event`, `metadata`, `session`, `target`, `agent`, `correlation_id`, `subject`.
4. Add snapshot/lint-style test for top-level context keys so deployed templates do not break from accidental renames.
5. Event builder: FIRST verify real emitted payload shape of `planning.item.created` (planning/events.py publishes item identity as `metadata.subject.id`; confirm whether payload carries top-level `id`). Map planning item identity to stable `{plan_item.id}` from payload or subject if that alias is retained.
6. Non-event builders: allow code/API/CLI/MCP callers to pass `context` object data that becomes `{session.*}`, `{target.*}`, or `{launch.input.*}` after allowlist/redaction.
7. Clarify session input source: load from `session_input_store.py` when a session id is provided; otherwise use caller-supplied session data without persistence.
8. Preserve only safe/redacted fields; denylist sensitive keys (tokens/secrets/passwords/credentials) and enforce size limits such as 4KB per context section unless a different project standard exists.
9. Coordinate a single consolidated `prompt-launch-request.schema.json` update with EDJ03/EDJ11 for `context`, `agent-profile-id`, and `prompt-template-file` rather than three incompatible schema edits.
10. Integrate builder into `prompt_launch.py` between parse/validation and render/build job record so all job-launch paths use the same injection path.
11. Add tests for context produced from `planning.item.created`, direct prompt launch with explicit context, missing optional session data, redaction, and correlation propagation.

## Files

src/audiagentic/components/agent_jobs/prompt_context.py
src/audiagentic/components/agent_jobs/session_input_store.py
src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/components/agent_jobs/contracts/prompt-launch-request.schema.json
tests/unit/jobs/test_prompt_context.py
src/audiagentic/components/planning/events.py (read-only dependency)

## Validation

Unit tests for shared context keys, snapshot/key stability, live planning event envelope shape, planning item id injection, direct launch context injection, metadata/correlation propagation, redaction denylist, size limits, session store integration/absence, and missing optional session data.

## Effort & Risk

Medium. Need stable key naming before templates depend on it.

## Standards

arch-standards — stable key naming before templates depend on it; redact/limit fields (no raw large-record dumps by default); AudiaGenticError at boundary.
component-creation — context construction owned by agent-jobs, kept separate from rendering (EDJ06).

## Notes

This is the layer prompts reference; keep rendering separate from context construction. NOTE: `planning.item.created` carries subject identity in `metadata.subject.{kind,id}` (planning/events.py) — confirm payload-level `id` existence before wiring `{event.payload.id}` into the flagship EDJ09 example. Preferred example key is `{plan_item.id}`.

## Ledger Events

- chg_20260710_085734_created-seven-critical-edj-rev_7918
