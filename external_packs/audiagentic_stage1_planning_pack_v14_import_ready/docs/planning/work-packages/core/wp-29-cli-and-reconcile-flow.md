---
id: wp-29
label: Freeze CLI contract and reconcile flow
state: draft
summary: Freeze command surface, output envelopes, resolution order, validation categories, preservation behavior, and thin-dispatch rules for the existing CLI.
plan_ref: plan-23
task_refs:
- ref: task-350
  seq: 1000
- ref: task-351
  seq: 2000
- ref: task-352
  seq: 3000
- ref: task-360
  seq: 4000
standard_refs:
- standard-6
- standard-8
- standard-11
workflow: strict
---

# Objective

Make operator behavior explicit without letting the CLI become the installer runtime model.

# Scope of This Package

This package freezes the CLI command surface, shared resolution and reconcile flow, validation categories, preservation behavior, thin-dispatch rules, and component disable/uninstall reconcile behavior for the existing CLI. It consumes architecture boundaries from `wp-28` and does not redefine them. It does not model backends or target kinds.

# Inputs

- request-32
- spec-80
- spec-82
- spec-85
- architecture outputs from `wp-28`
- component lifecycle manifest from `task-359`
- current `src/audiagentic/channels/cli/main.py`

# Required Outputs

- canonical command list and default modes
- JSON envelope shape and human-output rules
- shared resolve and reconcile flow for install/update/uninstall/status/doctor/validate
- user-visible error categories and preservation behavior
- component disable and uninstall reconcile contract with stage-one apply boundaries

# Instructions

1. Freeze command and flag contract (task-350).
2. Freeze shared resolution and reconcile flow (task-351).
3. Freeze validation categories and preservation behavior (task-352).
4. Freeze component disable and uninstall reconcile behavior and stage-one apply boundaries (task-360).
5. Ensure parser code stays thin; move business rules into resolver or validator design.
6. Verify `status` and `doctor` differ mainly in reporting depth, not in desired-state interpretation.

CLI packetization should consume architecture boundaries from `wp-28`, not redefine them.

# Acceptance Checks

- [ ] canonical command list and default modes are explicit
- [ ] JSON envelope shape and human-output rules are defined
- [ ] shared resolve and reconcile flow covers install/update/uninstall/status/doctor/validate
- [ ] user-visible error categories and preservation behavior are explicit
- [ ] CLI handlers dispatch to installer helpers rather than owning resolution logic
- [ ] `standard-11` surface-layer thinness rule is satisfied
- [ ] component disable reconcile contract covers all three `disable.effect` values with idempotency rule
- [ ] uninstall reconcile contract covers preservation policy and step ordering
- [ ] stage-one apply boundaries table is complete with deferred operations justified

# Non-Goals

- no backend-specific target modeling
- no artifact-package matrix
- no final regression packet split

# Super-junior guidance

- keep parser code thin
- if adding logic feels like “business rules in argparse,” stop and move that rule into resolver or validator design
- status and doctor should differ mainly in reporting depth, not in how desired-state is interpreted

# Done means

- a junior implementor could add CLI behavior without inventing defaults or envelopes
- a reviewer can tell whether new CLI code is improperly owning resolution logic
