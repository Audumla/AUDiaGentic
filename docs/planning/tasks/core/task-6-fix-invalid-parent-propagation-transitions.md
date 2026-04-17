---
id: task-6
label: Fix invalid parent propagation transitions
state: done
summary: Prevent automatic propagation from attempting invalid parent state transitions
  such as draft -> done during event-driven cascades
domain: core
spec_ref: spec-20
request_refs:
- request-18
standard_refs:
- standard-5
- standard-6
---





# Description

Observed on 2026-04-17 while updating planning records through the planning MCP layer. Automatic propagation attempted invalid parent transitions like `draft -> done` for parent items after child task state changes. Bus logs showed failures from `PlanningAPI.state()` rejecting the propagated transition. This task isolates the root-cause fix in propagation rule evaluation/application so automatic parent updates only request workflow-valid target states or step parents through valid intermediate states.

# Acceptance Criteria

- Reproduction exists for the observed invalid propagation path (`draft -> done` on parent items)
- Propagation no longer requests workflow-invalid target transitions
- Parent items either remain unchanged when no valid automatic transition exists, or move only through workflow-valid states
- Regression test covers child state changes that previously triggered invalid parent transitions
- MCP/planning edits that change child task states no longer emit propagation errors for this scenario

# Notes
Related evidence: bus logs during 2026-04-17 planning updates showed `invalid transition draft -> done` raised from `src/audiagentic/planning/app/api.py:state()` via `src/audiagentic/planning/app/propagation.py:apply_propagation()`.

Implemented on 2026-04-17:
- `PlanningAPI._on_state_change_for_propagation()` now forwards event metadata into propagation evaluation so guard logic can use caller context consistently.
- `StatePropagationEngine.apply_propagation()` now skips workflow-invalid target transitions before calling `PlanningAPI.state()`.
- Added regression coverage in `tests/integration/test_propagation.py` for original `draft -> done` parent-jump bug.
- Refreshed propagation/healing integration fixtures to use current planning rules and valid rule import paths; targeted suites now pass.

Verification:
- `pytest tests/integration/test_propagation.py -q` -> 10 passed
- `pytest tests/integration/test_healing.py -q` -> 5 passed
