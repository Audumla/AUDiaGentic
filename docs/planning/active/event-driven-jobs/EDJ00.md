---
id: EDJ00
order: 0
plan: plan-event-driven-jobs
state: pending
validate-first: false
priority: P1
complexity: simple
created-by: claude
---

# Event-driven jobs — plan overview and implementation order

## Description

Coordination artifact for the event-driven-jobs plan (pattern: RS00). Read this FIRST before implementing any EDJ item. Goal: configured event-bus triggers launch durable agent jobs whose instructions are dispatched to the agents LLM gateway asynchronously, with outcomes propagated back to job state and full correlation/observability end-to-end. Architecture in one paragraph: agent-jobs subscribes to configured event patterns (EDJ01/EDJ02), renders a prompt from a stable context (EDJ06/EDJ10/EDJ11), creates a durable job record with event provenance (EDJ03), dispatches by PUBLISHING `agents.llm.gateway.requested` — never by importing agents' API (EDJ04) — and applies gateway lifecycle outcomes to job state (EDJ05). Standards/primitives that gate the spine: schema ownership (EDJ19), shared operational-record writer (EDJ20), async error standard + dead-letter (EDJ12), canonical timelines (EDJ07). Design-decision items (EDJ08/EDJ13/EDJ15/EDJ21) produce documented decisions, not speculative code.

## Steps

IMPLEMENTATION ORDER — dependency-driven; where this sequence and an item's `order` key disagree, THIS sequence wins.

Phase 0 — gate (must land first):
1. EDJ19 schema ownership + mirror-drift test (gates EDJ01, EDJ03, EDJ11)

Phase 1 — primitives:
2. EDJ01 trigger config + schema (component-only per EDJ19 default)
3. EDJ06 dotted-path renderer (foundation/templates.py, additive, shaped for EDJ21 delegation)
4. EDJ10 prompt context object (verify real planning.item.created payload FIRST)

Phase 2 — failure + observability primitives (before the observer, so EDJ02 never writes stub records):
5. EDJ20 shared append-only operational-record helper
6. EDJ12 async error standard + dead_letter.py (uses EDJ20)

Phase 3 — firing path:
7. EDJ02 event observer (subscribes, correlation doctrine, dead-letters via EDJ12, audit entries per EDJ14 shape)
8. EDJ11 file-loaded prompt templates (path containment in-scope)

Phase 4 — spine (complex items; strict order, review gate between each):
9. EDJ07 canonical timeline helper + event-name set (EDJ03 consumes it — land first)
10. EDJ03 durable job records with event provenance (extends job-record schema in BOTH mirror copies per EDJ19)
11. EDJ04 dispatch via published gateway event (blocking=false always; review gate: no agents_gateway_api import)
12. EDJ05 outcome propagation (explicit transitions; running-at-dispatch invariant from EDJ04)

Phase 5 — operator surface + docs:
13. EDJ14 trigger audit aggregation + event_jobs_overview
14. EDJ09 doctrine/README/examples (needs real schema names from EDJ01)

Phase 6 — design decisions (non-blocking, any order):
15. EDJ08 propagation-engine evaluation
16. EDJ13 gateway shared-service readiness review
17. EDJ15 extended trigger sources / payload filters
18. EDJ21 actions.render consolidation (only after EDJ06 is stable; characterization-test gated)

CROSS-CUTTING RULES (apply to every item):
- Every new error code registered in agent-jobs error-resolutions.yaml BEFORE first use (arch-standards §8).
- Correlation doctrine (EDJ02): propagate inbound correlation_id or generate at firing; join keys everywhere are job-id / correlation_id / trigger-id / request-id.
- Gateway access is events-only; nothing may assume same-process gateway internals (keeps EDJ13 future open).
- Bus handlers never raise; failures dead-letter (EDJ12).
- No speculative building: `kind` discriminator, filters, retry/replay, metrics are decision-gated (EDJ15/EDJ12/EDJ14 boundaries).

## Files



## Validation

Kept current as items complete: when an item lands, tick it here (edit this item via plan_update_item) and note any sequence deviation with rationale. This item is completed LAST, when all EDJ items are completed or explicitly deleted/superseded.

## Effort & Risk

None — coordination artifact only; no code.

## Standards

arch-standards; observability-standards; component-creation — the per-item standards fields are authoritative; this item just indexes them.

## Notes

Reviews to date: RV230 (→EDJ20), RV231 (→EDJ19), RV232 (→EDJ21) — all closed and incorporated. Implementer note: items are written for autonomous implementation — field lists, payload shapes, and transitions in each item are exact and grounded in code as of 2026-07-10; if the codebase has drifted, verify against the named modules before coding (each item names its read-only dependencies).

## Ledger Events


