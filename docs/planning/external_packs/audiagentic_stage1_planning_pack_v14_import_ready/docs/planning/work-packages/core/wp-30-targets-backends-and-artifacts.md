---
id: wp-30
label: Freeze targets, backends, overlays, and artifacts
state: draft
summary: Freeze external target modeling, backend compatibility, overlay rules, dependency scope, and artifact-centric delivery expectations.
plan_ref: plan-23
task_refs:
- ref: task-353
  seq: 1000
- ref: task-354
  seq: 2000
- ref: task-355
  seq: 3000
standard_refs:
- standard-6
- standard-8
- standard-11
workflow: strict
---

# Objective

Keep future extensibility in registries and backend contracts instead of product-specific namespaces.

# Scope of This Package

This package freezes external target modeling, backend compatibility, overlay rules, dependency scope, and artifact-centric delivery expectations. It consumes architecture boundaries from `wp-28` and CLI/resolution assumptions from `wp-29`. It does not design regression suites or final packet file lists.

# Inputs

- request-32
- spec-83
- architecture outputs from `wp-28`
- CLI and resolution assumptions from `wp-29`
- current release and lifecycle surfaces

# Required Outputs

- target/dependency namespace rules
- backend and overlay modeling rules
- artifact-form expectations
- stage-one apply versus plan-only boundaries

# Instructions

1. Separate namespaces for components, targets, dependencies, and realized capabilities (task-353).
2. Freeze backend, overlay, and artifact axes (task-354).
3. Decide stage-one apply boundaries for target kinds (task-355).
4. Do not let current VS Code or self-hosting assumptions define the generic model.
5. If two concepts have different lifecycle semantics, give them different namespaces.

# Acceptance Checks

- [ ] target/dependency namespace rules are explicit
- [ ] backend and overlay modeling rules are defined
- [ ] artifact-form expectations are stated
- [ ] stage-one apply versus plan-only boundaries are explicit
- [ ] internal component ids do not double as external target ids
- [ ] realized capability is modeled as an outcome, not a configured definition
- [ ] `standard-11` namespace separation and config-driven rules are satisfied

# Non-Goals

- no final packet file list
- no import renumbering
- no live external system integration tests

# Super-junior guidance

- if two concepts have different lifecycle semantics, give them different namespaces
- if one backend works for one target today, do not assume it fits all future targets
- model realized capability as an outcome, not as a requested definition

# Done means

- a later implementor can create schemas and compatibility checks without re-asking what a target, dependency, overlay, or artifact is
- a reviewer can spot AUDia-only leakage into generic installer design
