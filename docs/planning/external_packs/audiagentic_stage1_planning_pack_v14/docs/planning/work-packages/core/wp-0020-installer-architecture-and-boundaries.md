---
id: wp-0020
label: Freeze installer architecture and ownership boundaries
state: draft
summary: Freeze installer nouns, layering, registry ownership, current-product versus platform boundaries, desired-state concepts, and migration guardrails.
plan_ref: plan-0017
task_refs:
- ref: task-0251
  seq: 1000
- ref: task-0252
  seq: 2000
- ref: task-0253
  seq: 3000
standard_refs:
- standard-06
- standard-11
workflow: strict
---

# Objective

Make architecture decisions explicit before CLI, target, or verification work is packetized.

# Scope of This Package

This package freezes installer nouns, layering, registry ownership, current-product versus platform boundaries, desired-state concepts, and migration guardrails. It produces the architectural foundation that `wp-0021` (CLI) and `wp-0022` (targets/backends) consume. It does not design CLI commands, target kinds, or regression suites.

# Inputs

- request-0032
- spec-0050
- spec-0051
- current repo CLI, lifecycle, config, and validation hot spots
- v13 review findings

# Required Outputs

- named list of current product-owned contracts
- named list of installer-owned registry groups
- explicit layer placement for installer concerns
- explicit migration and normalization boundaries

# Instructions

1. Survey current repo-owned contracts and hot spots (task-0251).
2. Define installer nouns and assign them to layers (task-0252).
3. Define registry ownership and migration guardrails (task-0253).
4. Review outputs against `standard-11` layering rules before freezing.

Do not start CLI or target-model packetization until this package is frozen.

# Acceptance Checks

- [ ] current product-owned contracts are named and separated from installer-owned definitions
- [ ] installer-owned registry groups are named
- [ ] each major installer concern has a target layer
- [ ] migration and normalization boundaries are explicit
- [ ] no spec or task drifts toward hardcoded canonical-id ownership
- [ ] `standard-11` layering rules are satisfied (no inward-to-outward imports, config-driven, extension points defined)

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
