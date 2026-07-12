---
id: EDJ15
order: 90
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P2
complexity: mid
created-by: claude
---

# Payload filter conditions for event triggers

## Description

Implement optional payload/metadata filter conditions on event triggers. Concrete consumer: without filters, every `planning.item.created` fires an LLM job regardless of priority — cost and noise. A trigger should be able to declare e.g. 'only fire when payload.priority is P0 or P1'. Scope is deliberately minimal: equality/inclusion matching on dotted paths; NO expression language, no comparisons, no boolean composition beyond implicit AND.

## Steps

1. Extend component-owned `event-trigger.schema.json` only. `filter` is optional object whose keys match non-empty dotted paths and values are scalar `string|integer|boolean` or non-empty lists of one scalar type; reject null, object, nested list, and mixed-type lists through schema validation. Event-trigger schema stays component-only; do not create foundation mirror.
2. In `foundation/templates.py`, extract its existing dotted lookup into public `resolve_path(context: Mapping[str, Any], path: str) -> Any | _MISSING`; `_MISSING` is exported only for internal/foundation consumers, not config. `render_template` calls this exact helper. It must distinguish missing path from present `None`, preserve existing template errors/behavior, and never use `foundation.refs`.
3. Add `matches_filter(context, filter_spec) -> bool` in `event_triggers.py`, not observer. Evaluation context is exactly `{"payload": payload, "metadata": metadata}` after observer copies metadata. Each key resolves through `resolve_path`; scalar uses equality, list uses membership; all clauses AND. Missing path, None, or mismatch returns false; no exception.
4. In `_on_trigger_match`, evaluate after correlation resolution and disabled check but before `_dispatch`. On false, write one audit entry `status="suppressed"`, `reason="filter"`, same trigger/event/correlation identifiers; create no job and publish no request. Extend `_write_trigger_audit` with optional `reason` field; existing callers omit it.
5. Register a new validation error only if runtime validation supplements schema. Do not add comparison/regex/OR/expression syntax. Update EDJ09 example only after implementation.
6. Tests use one shared context fixture to prove `resolve_path`, template interpolation, and filters agree on dotted paths; cover scalar/list/AND/missing/None, audit reason, schema rejection, and unchanged template tests.

## Files

src/audiagentic/components/agent_jobs/contracts/event-trigger.schema.json
src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/foundation/templates.py (shared path resolution)
tests/unit/jobs/test_event_triggers.py
tests/unit/jobs/test_event_observer.py

## Validation

Unit tests: scalar equality match fires; list membership fires; non-matching value suppressed with audit status=suppressed reason=filter; missing dotted path suppressed (no error); multiple filter keys AND; invalid filter value type rejected at load with registered code; resolve_path semantics proven identical between filter evaluation and render_template (shared fixture); render_template behavior unchanged after the extraction (existing template tests green).

## Effort & Risk

Medium-small. Guardrail: any request for operators beyond equality/membership (>, regex, OR) is out of scope — reject and note here. Non-event trigger kinds (schedule/webhook/file-watch) remain out of scope entirely: no consumer exists; the `kind` discriminator already reserves the room (see notes).

## Standards

arch-standards — config-over-code, registered error codes, no speculative expression language.
observability-standards — suppression is auditable (audit entry with reason).

## Notes

Converted from a design gate to implementation per RV254: the filter half gained a real consumer (priority-gated planning triggers); the non-event-kinds half stays deferred with no plan item until a consumer appears — EDJ01's `kind` field is the reserved extension point.
DEPENDS ON EDJ23 (FIX 1 + FIX 2): filters require per-trigger subscription (multiple triggers on one pattern with different filters) and the reachable suppression-audit path — both are broken today and fixed there.
FIELD-NAME PRECISION: the implemented audit record uses `status` (values fired/suppressed/failed), not `outcome` — write suppressed-by-filter entries as status=suppressed with an additive `reason: "filter"` field alongside the existing error_code/error_message fields (see _write_trigger_audit in event_observer.py for the authoritative shape).

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_055003_event-triggers-can-now-declare_6937
