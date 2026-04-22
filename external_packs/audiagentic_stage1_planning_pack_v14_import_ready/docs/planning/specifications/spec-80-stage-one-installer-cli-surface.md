---
id: spec-80
label: Stage-one installer CLI surface
state: draft
summary: Define the operator-facing CLI contract as a thin extension of the existing `audiagentic` surface with safe defaults, explicit modes, project targeting, target selection, and clean JSON versus human output behavior.
request_refs:
- request-32
standard_refs:
- standard-6
- standard-8
- standard-11
---

# Purpose

Freeze the CLI contract without turning CLI handlers into the installer source of truth.

# Discovery requirement

Before freezing the CLI contract, survey the current CLI implementation in `src/audiagentic/channels/cli/main.py` and document:
- current entrypoint function
- current dispatch pattern
- current output handling
- which parts can be extended without replacing the existing CLI

If the current CLI shape differs materially from this spec, record that as a blocker rather than silently redefining the live behavior.

# Scope

This spec covers the operator-facing CLI command set, flags, execution semantics, and output envelopes for the stage-one installer surface. It extends the existing `audiagentic` CLI entrypoint; it does not define a parallel installer CLI.

# Constraints

- Must extend `src/audiagentic/channels/cli/main.py`; must not create a second installer entrypoint.
- JSON output must never include banners or decorative text.
- Command handlers must resolve installer definitions through registry and resolution layers, not hardcoded target logic.
- Must not replace the existing `audiagentic` entrypoint.
- Must not embed registry contents in CLI command handlers.
- Must not make target selection mandatory for current project-only behavior.

# Requirements

## Commands

The stage-one surface must provide:
- `audiagentic install`
- `audiagentic update`
- `audiagentic uninstall`
- `audiagentic status`
- `audiagentic doctor`

## Flags

Mutating commands must support:
- `--project-root PATH`
- `--mode plan|apply|validate`
- `--profile PROFILE_ID`
- repeatable `--component COMPONENT_ID`
- repeatable `--disable-component COMPONENT_ID`
- repeatable `--target TARGET_ID`
- `--json`

Diagnostics commands must support:
- `--project-root PATH`
- `--json`
- optional `--verbose`

## Surface constraints

- extend `src/audiagentic/channels/cli/main.py`; do not create a parallel installer CLI
- keep `main.py` thin; dispatch into installer-specific helpers
- JSON output must never include banners or decorative text
- command handlers must resolve installer definitions through registry and resolution layers, not hardcoded target logic

## Execution semantics

- `install`, `update`, and `uninstall` default to `--mode plan`
- `status` and `doctor` are always non-mutating
- `plan` mode produces intended actions without mutation
- `apply` mode executes backend handlers only after desired-state and compatibility resolution succeed
- `validate` mode runs the same resolution and compatibility checks as `plan` without mutation output requirements

## Output contract

- human output may contain banners, headings, summaries, and remediation hints
- JSON output must be envelope-based and machine-stable
- envelope should include command, mode, project root, selected profile, selected targets, status summary, findings, and planned or executed steps
- errors must stay specific enough to distinguish malformed input, unknown references, unsupported combinations, and runtime execution failures

## Likely implementation surfaces

- `src/audiagentic/channels/cli/main.py`
- new installer CLI helper under `src/audiagentic/channels/cli/`
- shared output helpers for human versus JSON rendering
- resolution and planning hooks under `src/audiagentic/runtime/lifecycle/` or adjacent installer modules

## Do not change in this slice

- do not replace the existing `audiagentic` entrypoint
- do not embed registry contents in CLI command handlers
- do not make JSON output depend on banner or terminal formatting helpers
- do not make target selection mandatory for current project-only behavior

## Verification expectations

- command parsing tests for each canonical command
- mode-default tests for mutating commands
- JSON-envelope tests proving no banner contamination
- integration check proving thin dispatch into non-CLI helpers
- negative tests for unknown profiles, unknown targets, and invalid mode combinations

# Acceptance Criteria

- [ ] command set is explicit
- [ ] flag set is explicit
- [ ] JSON versus human output rules are explicit
- [ ] thin-surface rule is explicit
- [ ] execution semantics are explicit
- [ ] likely implementation surfaces are explicit
- [ ] verification expectations are explicit
