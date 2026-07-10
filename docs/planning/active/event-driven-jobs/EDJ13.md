---
id: EDJ13
order: 120
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P2
complexity: mid
created-by: claude
---

# Gateway shared-service readiness review (multi-instance scheduling)

## Description

The gateway may soon be accessed as a shared service so many process instances can use its scheduling. Today it is strictly in-process: module-level GatewayQueueManager, per-profile thread pools/semaphores, blocking wait() only works in the submitting process, and reconcile_gateway_state assumes single ownership of the store (a restart marks running->failed — wrong if another instance is legitimately running them). This is a DESIGN review item: decide the shared-service shape and enumerate the changes, do not build it yet.

## Steps

1. Inventory the same-process assumptions: _QUEUE_MANAGER module global, wait/cancel via in-memory manager, MAX_BLOCKING_TIMEOUT semantics, file-store per project_root with no lease/ownership marker, reconcile_gateway_state orphan logic.
2. Decide the multi-instance submission surface. The event path (`agents.llm.gateway.requested` -> lifecycle events) is already location-transparent — confirm it as THE cross-instance contract; blocking submit/run/wait remain same-process conveniences only.
3. Design queue ownership for many submitters / one (or more) dispatcher: request records need an owner/lease field so reconcile only orphans records whose owning instance is dead; define idempotency key on submit so re-published request events do not double-dispatch.
4. Assess blocking/async impact: document that blocking mode CANNOT be offered cross-instance without a wait-by-polling or callback-event design; event-triggered jobs are already async-only (EDJ01/EDJ04) so they are unaffected — confirm no EDJ01-EDJ11 work assumes same-process gateway access.
5. Correlation: confirm metadata (job-id, correlation_id, subject) echoes intact across instance boundaries via lifecycle events — it is the only correlation channel once callers are remote.
6. Record the recommendation + follow-up implementation items (store leasing, submit idempotency, remote status surface) as new plan entries if adoption is agreed.

## Files

src/audiagentic/components/agents/agents_gateway_api.py
src/audiagentic/components/agents/agents_gateway_queue.py
src/audiagentic/components/agents/agents_gateway_store.py
src/audiagentic/components/agents/agents_gateway_events.py
docs/standards/ARCHITECTURE_STANDARDS.md

## Validation

Design review item: a documented decision covering submission surface, lease/ownership model, idempotency, blocking semantics, and correlation across instances; plus explicit confirmation (or fixes) that EDJ01-EDJ11 introduce no same-process gateway coupling.

## Effort & Risk

Medium. Risk is over-designing distributed infrastructure before a second instance exists — output is a decision + follow-up items, not code. The one thing v1 items must already honor: gateway access via events only.

## Standards

arch-standards — component layering; config-over-code; avoid premature abstraction.
observability-standards — correlation keys must survive the instance boundary.

## Notes

Called out during 2026-07-10 critical review at user request. Does not block EDJ01-EDJ11; those items were shaped to be compatible (async-only triggers, event-based dispatch, metadata correlation).

## Ledger Events


