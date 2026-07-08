---
id: EDJ11
order: 50
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: mid
---

# Load event-trigger prompt templates from files

## Description

Allow event trigger prompt content to be externalized into files instead of inline YAML. Triggers should support either `prompt-template` inline content or `prompt-template-file` pointing to a project file, then render with the event prompt context.

## Steps

1. Extend trigger schema with `prompt-template-file`.
2. Resolve files relative to project root, with optional managed defaults under `.audiagentic/prompts/events/`.
3. Enforce path containment IN THIS ITEM: reject resolved paths that escape the project root (traversal / absolute / symlink escape) with AudiaGenticError. This guardrail ships with the feature — it is not deferred.
4. Require exactly one of inline template or file template.
5. Load text safely with clear IO errors.
6. Render using dotted-path replacement keys from EDJ06/EDJ10.

## Files

src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/prompt_templates.py
src/audiagentic/components/agent_jobs/contracts/event-trigger.schema.json
tests/unit/jobs/test_event_triggers.py

## Validation

Unit tests for inline template, file template, relative path resolution, missing file errors, mutually exclusive config validation, AND path-containment rejection (../ escape, absolute path outside root).

## Effort & Risk

Medium. Path containment is in-scope, not deferred — config must not read outside project root. Any future opt-in to broaden allowed roots is a separate item.

## Standards



## Notes

This lets config stay concise while prompt content lives in versioned markdown files. Containment check lands with the file loader (see step 3).
