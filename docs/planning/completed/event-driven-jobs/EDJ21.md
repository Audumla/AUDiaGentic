---
id: EDJ21
order: 135
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P3
complexity: simple
created-by: claude
---

# Consolidate workflow.actions.render onto shared template core

## Description

From RV232: after EDJ06 lands foundation/templates.py, two renderers with overlapping typed whole-placeholder / mixed-string behavior will exist (templates.py and foundation.workflow.actions.render). Migrate actions.render to delegate to the shared template core — ONLY if its existing behavior is fully preserved under compatibility tests. This is a follow-up; EDJ06 stays additive.

## Steps

1. First create `tests/unit/foundation/test_actions_render_compat.py` from current `foundation.workflow.actions.render` behavior. Cover whole-placeholder type preservation, mixed-string coercion, nested mappings/lists, missing simple key, missing dotted key, literal braces, and invalid input. Characterization expected values come from current implementation—not desired behavior.
2. Run characterization tests before source edits and record command/result in item notes. If any test is unstable, fix fixture only; do not alter actions.render behavior.
3. Replace only actions.render internals with a thin adapter to `foundation.templates.render_template`. Adapter translates workflow's simple-key context/placeholder contract into shared core inputs without caller changes. Preserve public signature, return types, and exception class/message behavior; no caller edits.
4. If any characterized behavior cannot be expressed through a small adapter/options addition in shared core, stop. Revert source migration, keep tests, update EDJ21 notes with divergent case and set item pending; do not maintain a second renderer or broaden shared template behavior speculatively.
5. Add concise docstrings distinguishing `foundation.refs.resolve_ref` (module:object config reference) from `foundation.templates` (data-path substitution). No code imports across that boundary.
6. Validate characterization + existing `tests/unit/foundation/test_templates.py` + workflow unit suite. Mark complete only after all pass; otherwise retain tests and documented stop reason.

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

From review RV232 (codex); absorbs duplicate item EDJ18 (codex).

RESOLVED 2026-07-12 — STOP DECISION (step 4 gate fired). Characterization command/result: `python -m pytest tests/unit/foundation/test_actions_render_compat.py tests/unit/foundation/test_templates.py tests/unit/foundation/workflow -q` — all green before analysis; no source migration was performed, so they remain green.

Divergent cases that block delegation to foundation.templates.render_template:
1. Typed whole-placeholder preservation: actions.render('{count}', {'count': 7}) returns int 7 and returns dicts/lists by identity; render_template always returns a string (dicts/lists become json.dumps).
2. Mixed-string semantics are str.format: format specs ('{n:03d}' -> '007'), literal-brace escaping ('{{these}}' -> '{these}'), and str() coercion of dict values ("{'a': 1}"); render_template's regex has none of these — '{{x}}' resolves as a bogus path and raises VAL-TPL-001, and dict values render as JSON.
3. Error contract: VAL-WFACT-001/002 vs VAL-TPL-001 (translatable, but moot given 1–2).

A 'thin adapter' reproducing these would re-implement the whole current renderer (or embed a second renderer behind flags in the shared core) — exactly what the item forbids ('do not maintain a second renderer or broaden shared template behavior speculatively'). Outcome kept per step 4: characterization tests retained at tests/unit/foundation/test_actions_render_compat.py as the permanent compatibility gate; cross-referencing docstrings added to actions.render and foundation/templates.py (including the refs.resolve_ref distinction). The two renderers serve different contracts (workflow simple-key typed rendering vs prompt dotted-path string rendering) — the RV232 duplication is superficial. Any future consolidation attempt must start from the characterization suite; do not resurrect this item — raise a fresh one.

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_101300_the-workflow-action-renderer-a_5102
