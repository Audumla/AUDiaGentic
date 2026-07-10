---
id: EDJ21
order: 135
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P3
complexity: simple
created-by: claude
---

# Consolidate workflow.actions.render onto shared template core

## Description

From RV232: after EDJ06 lands foundation/templates.py, two renderers with overlapping typed whole-placeholder / mixed-string behavior will exist (templates.py and foundation.workflow.actions.render). Migrate actions.render to delegate to the shared template core — ONLY if its existing behavior is fully preserved under compatibility tests. This is a follow-up; EDJ06 stays additive.

## Steps

1. Before migrating, snapshot current actions.render behavior as characterization tests (typed whole-placeholder, mixed strings, nested list/dict, missing-key behavior — whatever it does today, including quirks).
2. Reimplement actions.render as a thin wrapper over the EDJ06 template core; run the characterization suite — any divergence means stop and keep the two implementations, recording why in this item.
3. Keep the public signature and error behavior of actions.render unchanged; no caller edits.
4. Document the distinction from foundation.refs.resolve_ref (module:object config references) vs template rendering (dotted data paths in mapping context) in both modules' docstrings.

## Files

src/audiagentic/foundation/workflow/actions.py
src/audiagentic/foundation/templates.py
tests/unit/foundation/test_actions_render_compat.py

## Validation

Characterization tests written from CURRENT behavior pass before and after the migration; full existing workflow test suite green; docstrings state the refs vs templates distinction.

## Effort & Risk

Simple, but strictly conditional: the compatibility gate is the whole point — a behavior mismatch is a stop signal, not something to patch around. Depends on EDJ06.

## Standards

arch-standards — single shared capability in foundation, no behavior change at public boundaries.

## Notes

From review RV232 (codex). EDJ06 must design templates.py with this delegation in mind (pure function over mapping context, no workflow-specific coupling) — noted there.

## Ledger Events


