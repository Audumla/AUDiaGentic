---
id: EDJ23
order: 62
plan: event-driven-jobs
state: completed
validate-first: true
priority: P1
work: M
created-by: claude
---

# Event observer correctness fixes: per-trigger subscription, suppression audit, never-raise, stuck jobs

## Description

Four confirmed defects in the implemented event_observer.py / event_triggers.py, found in the 2026-07-12 deep review (RV244 plus three new findings). Each fix is small; they share the same modules and tests, so they land together.

## Steps

1. Remove `seen_patterns` entirely from `EventObserver.initialize`; subscribe once for every `TriggerConfig`, including same-pattern triggers. `_subscribed` remains sole duplicate-initialization guard. Update docstrings/tests from 'enabled patterns' to 'configured triggers'.
2. `load_event_triggers` returns every schema-valid trigger, including `enabled: false`; update its return contract/docstring. Add public `enabled_event_triggers(triggers: Sequence[TriggerConfig]) -> list[TriggerConfig]` only if a verified caller needs enabled-only data; otherwise no helper. Before edit, enumerate all callers with `rg`; update every affected test expectation. Observer subscribes disabled trigger and its existing suppression branch writes exactly one audit record, creates no job, and publishes no gateway request.
3. At entry to `_on_trigger_match` and `_handle_gateway_outcome`, replace `metadata = metadata or {}` with `metadata = dict(metadata or {})`. Never mutate inbound bus metadata.
4. `_handle_gateway_outcome` catches every exception, including `AudiaGenticError`: log with `exc_info=True`, best-effort `record_job_timeline_event(..., "job.gateway-outcome-received", state=current_state when known, attributes={event_type, reason})`, then `write_dead_letter`, then return. For an illegal transition, never force a transition; job state remains unchanged. Dead-letter error_code uses `exc.code` for `AudiaGenticError`, otherwise `INT-GW-001`; payload/metadata use EDJ24 safe helpers once available, or equivalent existing redacted identifier-only values until then.
5. Dispatch failure owns its job lifecycle. Immediately after `build_job_from_event`, keep local `job_id`. On any later render, job-file rewrite, transition, or publish error, best-effort transition that exact job to `failed`, then write `job.failed` timeline with only error code. Add config edges `created: [ready, failed]` and `ready: [running, cancelled, failed]`; do not add Python state-name branching. The gateway outcome handler must still refuse illegal created/ready → completed/cancelled propagation.
6. Preserve original exception for dead-letter/audit, never mask it with cleanup failure. No new error codes expected.

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/components/agent_jobs/event_triggers.py
src/audiagentic/components/agent_jobs/workflows.yaml
tests/unit/jobs/test_event_observer.py
tests/unit/jobs/test_event_triggers.py

## Validation

Tests per fix: (1) two triggers sharing one pattern BOTH fire on a matching event, one audit entry each; (2) disabled trigger produces a `suppressed` audit entry and no job; loader exposes disabled triggers, filter helper returns only enabled; (3) outcome event for a job in `created` does not raise, writes dead-letter + timeline, job state unchanged... then with FIX 4's edges, transitions created→failed become legal for the dispatch-failure path only — assert the outcome handler still refuses to jump created→completed; (4) forced render failure leaves job `failed` (not created) with timeline entry; forced publish failure leaves job `failed` (not running); (5) inbound metadata dict is not mutated (assert dict equality after handler runs). All existing observer/trigger tests still green.

## Effort & Risk

Medium. FIX 2 changes loader semantics — audit every load_event_triggers caller before changing (Grep for callers). FIX 4's workflow edge additions must not let the outcome handler use them (guard: only the dispatch failure path may drive created/ready→failed).

## Standards

arch-standards — async handlers never raise; registered error codes for any new codes; config-over-code (workflow edges in YAML).
observability-standards — suppression and failure are auditable; timeline entries carry correlation keys.

## Notes

From RV244 (codex) + three findings from the 2026-07-12 deep code review (per-pattern dedupe drops triggers; outcome handler re-raises; dispatch failures strand jobs in non-terminal states; shared metadata dict mutated). EDJ15 (filters) depends on FIX 1 and FIX 2 landing first — filters make shared patterns and suppression the norm.
FOUNDATION CAPABILITY (verified 2026-07-12, no bus/engine changes needed): the bus natively supports multiple subscribers per pattern (subscriptions are lists; FIX 1 is deleting our dedupe only); the bus already swallows ALL handler exceptions via SubscriberError (event_bus.py:291-314), so FIX 3's rationale is that a raise BYPASSES DEAD-LETTERING — auditability, not stability; the bus deliberately hands the SAME metadata dict to every subscriber (FIX 5 is correctly ours to fix); FIX 4's created/ready→failed edges are a workflows.yaml-only change (TransitionEngine is fully config-driven, `failed` already in state enum and terminal set).

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_052746_event-triggered-jobs-are-now-m_8720
