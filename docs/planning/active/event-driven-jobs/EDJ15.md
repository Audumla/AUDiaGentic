---
id: EDJ15
order: 130
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P3
complexity: simple
created-by: claude
---

# Extended trigger sources and payload filters (design decision)

## Description

Design item for extending triggering beyond bus events, using the additive headroom EDJ01 reserves (the `kind` discriminator). Candidates: payload filter conditions on event triggers (e.g. only planning items with priority P0/P1), and non-event kinds (schedule/cron, file-watch, webhook). Decide what earns implementation and specify the schema extension for each accepted kind — do NOT implement speculatively.

## Steps

1. Collect the concrete near-term needs (which filters/kinds have a real consumer today or in the next plan?).
2. For payload filters: specify an optional `filter` object on kind=event triggers — propose a minimal equality/inclusion match on dotted payload paths (reusing EDJ06 path semantics), explicitly rejecting a general expression language.
3. For each new kind: define its discriminated schema branch (e.g. kind=schedule -> `cron` field replaces `event-pattern`) and which existing machinery it reuses unchanged (context EDJ10, templates EDJ11, dispatch EDJ04, audit EDJ14 — only the firing source differs).
4. Record accept/reject per candidate with rationale; create implementation items only for accepted ones.

## Files

src/audiagentic/components/agent_jobs/contracts/event-trigger.schema.json
docs/planning/active/event-driven-jobs/

## Validation

Documented decision listing accepted/rejected extensions with rationale and, for accepted ones, the exact schema branch and new plan items created.

## Effort & Risk

Simple. The risk this item exists to prevent is both over-engineering (building kinds nobody uses) and under-engineering (an EDJ01 schema that cannot grow) — EDJ01's `kind` field already secures the latter, so this can safely wait.

## Standards

arch-standards — config-over-code; avoid premature abstraction.

## Notes

Called out during 2026-07-10 critical review: cater for triggering beyond current requirements. Does not block anything; EDJ01 must simply land with `kind` required.

## Ledger Events


