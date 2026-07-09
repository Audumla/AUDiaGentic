---
id: EDJ08
order: 100
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P2
complexity: simple
---

# Evaluate workflow propagation for job and gateway relationships

## Description

Review whether the foundation propagation engine should manage modeled job -> stage -> gateway request relationships after explicit event-triggered job flow lands. Document whether propagation adds value or creates unnecessary abstraction for the initial implementation.

## Steps

1. Model candidate relationships: job owns gateway request, job owns stages, stages produce gateway requests.
2. Analyze `foundation/workflow/propagation/engine.py` (`StatePropagationEngine.propagate()`) and related rule loading/config to determine whether job-record subjects can fit the existing interface.
3. Evaluate the propagation subject model in `parents.py`/workflow parent-child relationships against job -> gateway-request ownership, which is not a normal planning parent-child relation.
4. Compare explicit event handling against `StatePropagationEngine` rules.
5. Evaluate a hybrid option separately: event handling for real-time gateway outcomes, propagation for consistency repair/orphan detection.
6. Identify safe propagation cases: job cancelled -> gateway cancel, gateway completed -> job completed, gateway failed -> job failed.
7. Measure or estimate hot-path latency if propagation rules load/evaluate synchronously during job state transitions.
8. Record recommendation and follow-up implementation plan in `docs/architecture/decisions/event-driven-jobs-propagation.md` if beneficial.

## Files

src/audiagentic/foundation/workflow/propagation/engine.py
src/audiagentic/foundation/workflow/propagation/*
src/audiagentic/foundation/workflow/parents.py
src/audiagentic/components/agent_jobs/*
docs/standards/OBSERVABILITY_STANDARDS.md
docs/architecture/decisions/event-driven-jobs-propagation.md

## Validation

Design review item; validation is a documented decision with explicit criteria: subject-model fit, operational value, hot-path latency, failure modes, and test plan if a propagation prototype is added.

## Effort & Risk

Medium. Risk is overfitting generic propagation before relationships are durable enough.

## Standards

arch-standards — config-over-code and avoid premature abstraction (do not adopt generic propagation before relationships are durable).
observability-standards — decision recorded against OBSERVABILITY_STANDARDS.md.

## Notes

Do not block EDJ01-EDJ05; this is a second-pass architecture decision.
