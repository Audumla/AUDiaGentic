---
id: EDJ22
order: 60
plan: event-driven-jobs
state: completed
validate-first: true
priority: P0
work: S
created-by: claude
---

# Wire event observer into component lifecycle bootstrap

## Description

CRITICAL (RV243): the entire event-driven jobs capability is currently dead in production. src/audiagentic/config/components/agent-jobs.yaml has NO lifecycle-observer entry, and nothing in register_all_components() imports event_observer or calls get_event_observer() — so configured triggers never subscribe during normal bootstrap. The feature only runs from tests or manual calls.

## Steps

1. Study how existing components register lifecycle observers in their descriptors (compare providers.yaml / planning.yaml / agents.yaml in src/audiagentic/config/components/ — find the exact key and module-path convention).
2. Add the lifecycle-observer entry to agent-jobs.yaml pointing at audiagentic.components.agent_jobs.event_observer (or a thin bootstrap function in it) following that exact convention.
3. The bootstrap hook must call get_event_observer(project_root) — idempotency is already handled by the _subscribed flag; do not add a second guard.
4. Confirm the observer degrades safely when no event-triggers.yaml exists (load_event_triggers on a project without config must yield [] without error — verify, add a test if uncovered).

## Files

src/audiagentic/config/components/agent-jobs.yaml
src/audiagentic/components/agent_jobs/event_observer.py
tests/unit/jobs/test_event_observer_bootstrap.py

## Validation

Bootstrap test: register_all_components (or the narrower lifecycle-observer dispatch path other components' tests use) causes exactly one subscription set for enabled triggers; calling it twice does not double-subscribe; a project with no trigger config bootstraps without error. Manual verification per the verify skill: start the harness in a scratch project with one planning.item.created trigger and confirm a job record is created when the event fires.

## Effort & Risk

Simple but P0 — one descriptor line plus a test; the risk was shipping 'completed' items that cannot execute. Follow the established observer-registration pattern exactly; do not invent a new mechanism.

## Standards

component-creation — lifecycle-observer mechanism; config-over-code.
arch-standards — no import-time side effects beyond the established pattern.

## Notes

RV255 (2026-07-12): fixed and verified. `agent-jobs.yaml` now declares the lifecycle observer; event_observer self-registers for installed/enabled/config-changed and initializes the singleton through `get_event_observer(project_root)`. Unit test covers lifecycle initialization. Remaining observer defects remain in EDJ23.

## Ledger Events

- chg_20260712_051506_activate-configured-event-driv_5957
