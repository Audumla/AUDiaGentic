---
id: wp-28
label: Freeze installer architecture and ownership boundaries
state: draft
summary: Freeze installer nouns, layering, registry ownership, current-product versus platform boundaries, desired-state concepts, and migration guardrails.
plan_ref: plan-23
task_refs:
- ref: task-347
  seq: 1000
- ref: task-348
  seq: 2000
- ref: task-349
  seq: 3000
- ref: task-359
  seq: 4000
standard_refs:
- standard-6
- standard-11
workflow: strict
---

# Objective

Make architecture decisions explicit before CLI, target, or verification work is packetized.

# Scope of This Package

This package freezes installer nouns, layering, registry ownership, current-product versus platform boundaries, desired-state concepts, migration guardrails, and the component lifecycle manifest schema. It produces the architectural foundation that `wp-29` (CLI) and `wp-30` (targets/backends) consume. It does not design CLI commands, target kinds, or regression suites.

# Inputs

- request-32
- spec-81
- spec-82
- spec-85
- current repo CLI, lifecycle, config, and validation hot spots
- v13 review findings

# Required Outputs

- named list of current product-owned contracts
- named list of installer-owned registry groups
- explicit layer placement for installer concerns
- explicit migration and normalization boundaries
- canonical component lifecycle manifest schema validated against a live component

# Instructions

1. Survey current repo-owned contracts and hot spots (task-347).
2. Define installer nouns and assign them to layers (task-348).
3. Define registry ownership and migration guardrails (task-349).
4. Freeze component lifecycle manifest schema using knowledge component as reference case (task-359).
5. Review outputs against `standard-11` layering rules before freezing.

Do not start CLI or target-model packetization until this package is frozen.

# Acceptance Checks

- [ ] current product-owned contracts are named and separated from installer-owned definitions
- [ ] installer-owned registry groups are named
- [ ] each major installer concern has a target layer
- [ ] migration and normalization boundaries are explicit
- [ ] no spec or task drifts toward hardcoded canonical-id ownership
- [ ] `standard-11` layering rules are satisfied (no inward-to-outward imports, config-driven, extension points defined)
- [ ] component lifecycle manifest schema is validated against the knowledge component with every field sourced to a live file
- [ ] replacement slot pattern is documented

# Non-Goals

- no command-line design details beyond architecture impact
- no target-kind matrix yet
- no regression suite design yet

# Super-junior guidance

- treat current repo behavior as binding input, not as design inspiration to widen
- if unsure whether something is product-owned or installer-owned, keep it product-owned unless the spec explicitly moves it
- prefer adding a new resolver or registry seam over changing canonical-id or profile globals

# Done means

- a packet author can name where new installer logic belongs before editing code
- a reviewer can reject hardcoded growth by comparing proposed change against this package
