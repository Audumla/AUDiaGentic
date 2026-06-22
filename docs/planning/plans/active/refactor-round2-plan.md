---
id: plan-refactor-round2
label: Refactor round 2 (post-split)
state: draft
summary: Address duplication, misplaced logic, and cross-cutting concerns that survived the size pass
---

# Refactor round 2 (post-split)

Address duplication, misplaced logic, and cross-cutting concerns that survived the size pass

## Execution Order

Recommended: **A1 → A2 → B2 → B1 → A3**. B3 is investigate-only; C is opportunistic.

## Explicitly Rejected

- Merging the cwd-walking `_resolve_project_root` in logging/install into A1 (different logic)
- Splitting `event_bus.py`, `steps.py`, `provider_streaming.py` (cohesive)
- Blind merge of B3 before diffing (may be intentional per-harness variants)

## Items

- [R201](refactor-round2/R201.md)
- [R202](refactor-round2/R202.md)
- [R203](refactor-round2/R203.md)
- [R204](refactor-round2/R204.md)
- [R205](refactor-round2/R205.md)
- [R206](refactor-round2/R206.md)
