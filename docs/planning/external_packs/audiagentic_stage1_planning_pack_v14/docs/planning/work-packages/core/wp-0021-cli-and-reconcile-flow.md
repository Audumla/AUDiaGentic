---
id: wp-0021
label: Freeze CLI contract and reconcile flow
state: draft
summary: Freeze command surface, output envelopes, resolution order, validation categories, preservation behavior, and thin-dispatch rules for the existing CLI.
plan_ref: plan-0017
task_refs:
- ref: task-0254
  seq: 1000
- ref: task-0255
  seq: 2000
- ref: task-0256
  seq: 3000
standard_refs:
- standard-06
- standard-08
- standard-11
workflow: strict
---

# Objective

Make operator behavior explicit without letting the CLI become the installer runtime model.

# Scope of This Package

This package freezes the CLI command surface, shared resolution and reconcile flow, validation categories, preservation behavior, and thin-dispatch rules for the existing CLI. It consumes architecture boundaries from `wp-0020` and does not redefine them. It does not model backends or target kinds.

# Inputs

- request-0032
- spec-0049
- spec-0051
- architecture outputs from `wp-0020`
- current `src/audiagentic/channels/cli/main.py`

# Required Outputs

- canonical command list and default modes
- JSON envelope shape and human-output rules
- shared resolve and reconcile flow for install/update/status/doctor/validate
- user-visible error categories and preservation behavior

# Instructions

1. Freeze command and flag contract (task-0254).
2. Freeze shared resolution and reconcile flow (task-0255).
3. Freeze validation categories and preservation behavior (task-0256).
4. Ensure parser code stays thin; move business rules into resolver or validator design.
5. Verify `status` and `doctor` differ mainly in reporting depth, not in desired-state interpretation.

CLI packetization should consume architecture boundaries from `wp-0020`, not redefine them.

# Acceptance Checks

- [ ] canonical command list and default modes are explicit
- [ ] JSON envelope shape and human-output rules are defined
- [ ] shared resolve and reconcile flow covers install/update/status/doctor/validate
- [ ] user-visible error categories and preservation behavior are explicit
- [ ] CLI handlers dispatch to installer helpers rather than owning resolution logic
- [ ] `standard-11` surface-layer thinness rule is satisfied

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
