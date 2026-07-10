---
id: EDJ18
order: 26
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P2
complexity: simple
created-by: codex
---

# Consolidate workflow rendering onto shared template core

## Description

After EDJ06 adds `foundation/templates.py`, evaluate and migrate `foundation.workflow.actions.render` to delegate to the same rendering core without changing existing workflow behavior. This prevents two long-lived placeholder renderers with overlapping semantics.

## Steps

1. Reuse EDJ06 compatibility tests as the safety net for current `workflow.actions.render` behavior.
2. Add shared options or a thin compatibility wrapper so workflow placeholders keep current simple-key behavior while prompt templates can use dotted mapping paths.
3. Replace duplicated workflow render recursion/error handling with delegation to the shared core where behavior matches.
4. Keep `foundation.refs.resolve_ref` explicitly separate; do not use or rename it for data-path template lookup.

## Files

src/audiagentic/foundation/templates.py
src/audiagentic/foundation/workflow/actions.py
tests/unit/foundation/workflow/*
tests/unit/foundation/test_templates.py

## Validation

Existing workflow action render tests remain green; new tests prove dotted prompt template behavior and old workflow simple placeholder behavior do not diverge accidentally.

## Effort & Risk

Simple. Risk is accidental workflow behavior change; validate first and keep a compatibility wrapper if exact delegation is not clean.

## Standards



## Notes



## Ledger Events


