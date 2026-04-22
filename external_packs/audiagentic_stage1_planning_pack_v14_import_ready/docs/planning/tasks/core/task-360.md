---
id: task-360
label: Freeze disable and uninstall reconcile behavior
state: draft
summary: Define how the shared reconcile flow handles --disable-component and uninstall commands, including plan-step derivation, apply boundaries, and what stage one supports versus defers.
spec_ref: spec-85
request_refs:
- request-32
standard_refs:
- standard-5
- standard-6
- standard-8
- standard-11
---

# Description

The manifest schema (task-359) defines what a component declares. This task defines how the reconcile flow reads that manifest and turns it into plan steps for disable and uninstall operations. It also defines which operations reach `apply` in stage one and which stay `plan` or `doctor` only.

# Inputs

Read before starting:
- `spec-85` — component lifecycle manifest schema and semantics
- `spec-82` — resolution, validation, and reconcile flow
- `spec-80` — CLI surface and `--disable-component` flag
- `docs/installer/component-lifecycle-manifest.md` (output from task-359)
- `docs/installer/resolution-reconcile-contract.md` (output from task-351)
- `docs/installer/cli-command-contract.md` (output from task-350)
- `src/audiagentic/runtime/lifecycle/` — existing lifecycle modules

# Output

Produce `docs/installer/component-lifecycle-reconcile.md` with these sections:

## --disable-component flag behavior

Document how the reconcile flow handles `--disable-component COMPONENT_ID`:
- which commands accept it (`install`, `update`, `uninstall`)
- how it modifies desired-state before resolution runs
- what plan steps are generated per `disable.effect` value (`set_config_flag`, `remove_subscriptions`, `both`)
- how `--mode plan` renders disable steps (what the operator sees before apply)
- how `--mode apply` executes disable steps (order of operations)
- idempotency rule: running disable on an already-disabled component produces no-op steps, not an error

## uninstall command behavior

Document how `audiagentic uninstall` processes component manifests:
- default scope: all components with lifecycle manifests
- scoped uninstall: `--component COMPONENT_ID` limits to one component
- step derivation from `uninstall.effect` values (`remove`, `disable_only`)
- preservation policy: how `uninstall.preserves` paths are excluded from removal steps
- step ordering: subscriptions torn down before files removed, config keys removed last
- how `--mode plan` renders uninstall steps
- how `--mode apply` executes uninstall steps

## Stage-one apply boundaries

Document which lifecycle operations reach `apply` in stage one and which are deferred:

| Operation | Stage-one support | Notes |
|---|---|---|
| disable via config flag | apply | low-risk, reversible |
| disable via subscription teardown | apply | requires event bus available |
| uninstall (disable_only effect) | apply | equivalent to disable |
| uninstall file removal | plan only | apply deferred to later phase |
| python package removal | plan only | apply deferred to later phase |
| replacement slot activation | plan only | apply deferred to later phase |

For each deferred operation, document:
- why it is deferred (risk, dependency, or scope reason)
- what `--mode plan` shows the operator
- what a future phase must add to unlock apply

## Validation failures specific to lifecycle

For each failure case, document the exact error message category and remediation hint:
- component id not found in registry
- component has no lifecycle manifest
- `--disable-component` used with a diagnostic command (`status`, `doctor`)
- uninstall with `--mode apply` attempted for an operation beyond stage-one apply boundary
- preservation path conflict (user data path overlaps with owned directory)
- replacement slot collision (two components claim the same event subscription pattern)

## Interaction with shared reconcile flow

Document how lifecycle operations plug into the shared resolution contract from task-351:
- where in the resolution pipeline disable/uninstall desired-state is injected
- how lifecycle plan steps appear in the shared step object structure
- how lifecycle findings appear in the shared JSON envelope

# What not to change

- do not define manifest schema fields (belongs in task-359)
- do not change the 5-level precedence order from task-351
- do not define backend file-removal implementation (infrastructure concern)
- do not modify existing lifecycle modules in `src/audiagentic/runtime/lifecycle/`
- do not extend apply boundary beyond what is listed in the stage-one apply boundaries table
- do not add new CLI flags beyond those in spec-80

# Blocker handling

- if `docs/installer/resolution-reconcile-contract.md` is not yet complete, document the dependency and define lifecycle behavior against the spec-82 contract directly
- if event bus availability cannot be guaranteed at apply time, default subscription teardown to plan-only and record the constraint
- if the existing lifecycle modules conflict with the resolution flow defined here, record the conflict rather than silently reordering operations

# Acceptance criteria

- [ ] `--disable-component` flag behavior is documented for all three `disable.effect` values
- [ ] idempotency rule for disable is explicit
- [ ] uninstall step derivation covers both `remove` and `disable_only` effects
- [ ] preservation policy behavior is explicit for `uninstall.preserves` paths
- [ ] stage-one apply boundaries table is complete with a reason for each deferred operation
- [ ] all six validation failure cases have exact error message categories and remediation hints
- [ ] interaction with shared reconcile flow names the exact injection point in the resolution pipeline
- [ ] lifecycle plan steps use the same step object structure as the shared contract
- [ ] reviewer can verify deferred operations are not reachable via `--mode apply` in stage one
