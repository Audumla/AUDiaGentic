---
id: EDJ13
order: 120
plan: event-driven-jobs
state: completed
validate-first: true
priority: P2
work: M
created-by: claude
---

# Gateway shared-service readiness: boundary test + decision record

## Description

The gateway may be accessed as a shared service so many instances use its scheduling. Today it is in-process (module-level GatewayQueueManager; wait/cancel only work in the submitting process; reconcile_gateway_state assumes sole store ownership). This item produces two CONCRETE deliverables: (1) an executable architecture-boundary test enforcing events-only gateway access from agent_jobs, and (2) a written decision record at a named path with a required decision table. Implementation of leasing/idempotency etc. happens in follow-up items this item creates — not here.

## Steps

1. Deliverable A first: add `tests/unit/jobs/test_gateway_boundary.py`. Parse every non-test `src/audiagentic/components/agent_jobs/**/*.py` AST. Fail on imports/references to `agents_gateway_api`, `agents_gateway_queue`, `agents_gateway_store`, or `agents_gateway_dispatch`; also fail on imports of `agents_gateway_events`. Permit gateway event topic string literals only. Test must enumerate inspected files so a future module cannot evade scope.
2. Deliverable B: add `docs/design/gateway-shared-service.md`. This item is analysis-only: do not add leases, owner fields, idempotency fields, queues, migrations, or new event topics. Decisions must be based only on current code and named with file:symbol references.
3. Required sections and exact tables: `Same-process assumptions inventory` table columns `{location, current assumption, shared-service failure mode}`; `Decision table` columns `{concern, decision, rationale, follow-up item}`; `Non-goals`. Inventory must include `_QUEUE_MANAGER`, `wait_llm_request`, `cancel_llm_request`, `MAX_BLOCKING_TIMEOUT_SECONDS`, per-project-root store records, `reconcile_gateway_state`, and `EventBus._correlation_chains` retention.
4. Decision authority: record current v1 decision, not a speculative implementation: events are sole inter-component/cross-instance contract; direct blocking/wait/cancel APIs are same-process conveniences; multi-instance work is deferred until a second gateway instance is an approved requirement. Each deferred concern gets a separate pending plan item only when its decision table row requires code; otherwise `none`.
5. Link document from the gateway section of `src/audiagentic/components/agents/README.md`. No docs-generated files.

## Files

tests/unit/jobs/test_gateway_boundary.py
docs/design/gateway-shared-service.md
src/audiagentic/components/agents/README.md

## Validation

Boundary test exists and passes (and fails if a forbidden import is introduced into a scratch copy); design doc exists with all three required sections and a fully-populated decision table; every non-none follow-up row has a created plan item id; README links the doc.

## Effort & Risk

Medium. The test is mechanical; the doc requires judgment but the required sections/columns bound it. Risk of over-design is capped by the Non-goals section and by deferring all implementation to follow-up items.

## Standards

arch-standards — component layering, avoid premature abstraction.
observability-standards — correlation keys must survive the instance boundary (decision-table row).

## Notes

Converted from open-ended review to named deliverables per RV251. docs/design/ may not exist yet — create it; if the project has an established design-doc location discovered during implementation, use that instead and note the deviation here.
ADD TO THE ASSUMPTIONS INVENTORY (found 2026-07-12): EventBus._correlation_chains grows unboundedly per correlation id for the process lifetime (event_bus.py:347-359) — harmless for CLI-lifetime processes, but a long-lived shared gateway service process would leak memory and could eventually mis-trip cycle detection on very long correlation chains; the doc's inventory table needs a row for it.

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_055401_the-gateways-single-process-a_5255
