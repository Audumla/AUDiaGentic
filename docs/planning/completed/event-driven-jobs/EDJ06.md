---
id: EDJ06
order: 20
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P1
complexity: mid
---

# Add dotted-path template rendering for job prompts

## Description

Agent job prompt templates need placeholders like `{event.payload.id}`, `{plan_item.id}`, `{metadata.subject.id}`, `{job.id}`, and `{trigger.id}`. Add a reusable foundation renderer that supports dotted paths and hyphenated keys safely, then use it from the generic agent-job prompt assembly pipeline rather than from event triggers only.

## Steps

1. Add a NEW additive foundation template renderer at `foundation/templates.py` for dotted dict paths — do NOT modify `workflow.actions.render` semantics (existing callers depend on them).
2. Export the new module/function from `foundation/__init__.py` following foundation import conventions.
3. Support typed full-placeholder replacement and mixed string formatting.
4. Define hyphenated key syntax explicitly (e.g. `{event.payload.trigger-id}` if supported directly, or bracket notation if required) and test it.
5. Reject missing placeholders with AudiaGenticError using a dedicated VAL-TPL-* code; include placeholder path and nearby/available keys where safe.
6. Audit `agent_jobs/prompt_templates.py` and refactor existing agent-job string replacement to delegate to `foundation/templates.py`.
7. Use it from agent-jobs prompt assembly so event, code/API, CLI/MCP, and future scheduled triggers share one rendering path.
8. Keep renderer trigger-neutral: it receives a context mapping and never imports agent-jobs, planning, events, or agents.
9. Add compatibility tests proving existing `foundation.workflow.actions.render` callers do not change behavior when `foundation/templates.py` is present.

## Files

src/audiagentic/foundation/templates.py
src/audiagentic/foundation/__init__.py
src/audiagentic/components/agent_jobs/prompt_templates.py
src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/foundation/workflow/actions.py (read-only compatibility target)

## Validation

Unit tests for dotted path lookup, hyphenated key syntax, typed whole-placeholder rendering, missing keys with VAL-TPL-* AudiaGenticError, available-key diagnostics, and nested list/dict rendering. Compatibility tests for existing workflow.actions.render callers confirm no behavior change.

## Effort & Risk

Medium. Decision resolved: land as an additive `foundation/templates.py` helper rather than extending `foundation/workflow/actions.py`, to avoid any risk to existing workflow render semantics. workflow.actions may later delegate to this helper but that is out of scope here.

## Standards

arch-standards — additive foundation helper (no change to existing workflow.actions.render semantics); AudiaGenticError on missing placeholder, no raw KeyError/ValueError.
component-creation — rendering primitive lives in foundation, consumed by agent-jobs.

## Notes

Needed for readable config-driven prompts without custom Python per trigger.
Coordinate with EDJ10 (prompt context object) and EDJ11 (file-loaded templates); this item owns rendering mechanics, while those items own context construction and template source loading.
DESIGN CONSTRAINT (RV232/EDJ21): shape templates.py as the future shared core — a pure function over a mapping context with no workflow- or agent-jobs-specific coupling — so `workflow.actions.render` can later delegate to it under characterization tests (EDJ21). Do not migrate actions.render in this item.
NAMING: this renderer resolves dotted DATA paths inside prompt templates; `foundation.refs.resolve_ref` resolves `module:object` config references — unrelated mechanisms. State the distinction in the module docstring and keep test names unambiguous.

## Ledger Events

- chg_20260710_071837_added-dotted-path-template-ren_4226
- chg_20260710_085734_created-seven-critical-edj-rev_7918
