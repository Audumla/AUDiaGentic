---
id: EDJ06
order: 20
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: mid
---

# Add dotted-path template rendering for event payloads

## Description

Event trigger prompt templates need placeholders like `{payload.id}`, `{payload.created-by}`, `{metadata.subject.id}`, and `{trigger.id}`. Add a reusable foundation renderer or extend workflow action rendering to support dotted paths and hyphenated keys safely.

## Steps

1. Add a NEW additive foundation template renderer at `foundation/templates.py` for dotted dict paths — do NOT modify `workflow.actions.render` semantics (existing callers depend on them).
2. Support typed full-placeholder replacement and mixed string formatting.
3. Reject missing placeholders with AudiaGenticError.
4. Use it from agent-jobs event trigger prompt rendering.

## Files

src/audiagentic/foundation/templates.py
src/audiagentic/components/agent_jobs/event_triggers.py

## Validation

Unit tests for dotted path lookup, hyphenated keys, typed whole-placeholder rendering, missing keys, and nested list/dict rendering.

## Effort & Risk

Medium. Decision resolved: land as an additive `foundation/templates.py` helper rather than extending `foundation/workflow/actions.py`, to avoid any risk to existing workflow render semantics. workflow.actions may later delegate to this helper but that is out of scope here.

## Standards



## Notes

Needed for readable config-driven prompts without custom Python per trigger.
Coordinate with EDJ10 (prompt context object) and EDJ11 (file-loaded templates);
this item owns rendering mechanics, while those items own context construction
and template source loading.
