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
- standard-0006
- standard-0008
- standard-0011
workflow: strict
---

# Objective

Make operator behavior explicit without letting the CLI become the installer runtime model.
