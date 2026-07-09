---
id: EDJ11
order: 50
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: mid
---

# Load agent job prompt templates from files

## Description

Allow agent job prompt content to be externalized into files instead of inline config/request payloads. Event triggers, code/API launches, and CLI/MCP prompt launches should all resolve either inline `prompt-template`/`prompt-body` content or a `prompt-template-file`, then render with `AgentJobPromptContext`.

## Steps

1. Extend event trigger schema and prompt-launch request schema with `prompt-template-file`; update component and foundation schema copies plus registry/canonical ID mappings consistently.
2. Resolve files relative to project root, with optional managed defaults under `.audiagentic/prompts/jobs/` and event examples under `.audiagentic/prompts/jobs/events/`.
3. Add `.gitkeep` placeholders for managed prompt default directories if repository convention tracks empty directories.
4. Enforce path containment IN THIS ITEM: reject resolved paths that escape the project root (traversal / absolute / symlink escape) with AudiaGenticError. This guardrail ships with the feature — it is not deferred.
5. Implement containment via existing path safety utilities if present; otherwise add a focused helper (e.g. `foundation/path_safety.py`) handling realpath/symlinks, Windows case-insensitive drives, and Unicode normalization.
6. Require exactly one of inline template or file template; update schema oneOf/dependency constraints so existing v1 configs with both/neither still fail correctly.
7. Refactor `prompt_templates.py` to support both inline template content and file loading through one trigger-neutral loader.
8. Load text safely with clear IO errors.
9. Render using dotted-path replacement keys from EDJ06/EDJ10.
10. Keep loader trigger-neutral: event triggers call the same loader as direct job launches.
11. Add integration test for file load -> context build (EDJ10) -> dotted-path render (EDJ06).

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/prompt_templates.py
src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/components/agent_jobs/contracts/event-trigger.schema.json
src/audiagentic/components/agent_jobs/contracts/prompt-launch-request.schema.json
src/audiagentic/foundation/contracts/schemas/event-trigger.schema.json
src/audiagentic/foundation/contracts/schemas/prompt-launch-request.schema.json
src/audiagentic/foundation/contracts/schema_registry.py
src/audiagentic/foundation/contracts/canonical_ids.py
src/audiagentic/foundation/path_safety.py or existing path utility
.audiagentic/prompts/jobs/.gitkeep
.audiagentic/prompts/jobs/events/.gitkeep
tests/unit/jobs/test_event_triggers.py
tests/unit/jobs/test_prompt_templates.py

## Validation

Unit tests for inline template, file template, relative path resolution, direct launch file loading, event trigger file loading, missing file errors, mutually exclusive config validation, schema registry validation for both schema copies, v1 both/neither failures, AND path-containment rejection (`../` escape, absolute path outside root, symlink escape, Windows drive/case behavior where applicable). Integration test covers file load -> context build -> dotted-path render.

## Effort & Risk

Medium. Path containment is in-scope, not deferred — config must not read outside project root. Any future opt-in to broaden allowed roots is a separate item.

## Standards

arch-standards — path containment (reject resolved paths escaping project root); AudiaGenticError with clear IO error codes; config-over-code.
component-creation — template loader owned by agent-jobs; managed defaults under .audiagentic/prompts/jobs/.

## Notes

This lets config stay concise while prompt content lives in versioned markdown files. Containment check lands with the file loader (see step 3).
