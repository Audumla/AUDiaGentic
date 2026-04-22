---
id: plan-0017
label: Deliver a modular stage-one generic installer platform
state: draft
summary: Deliver the stage-one installer slice as four modular work packages covering architecture, CLI and reconcile flow, target/backend/artifact modeling, and regression foundations, while preserving current repo-owned contracts and enabling future extensibility through config and registries.
request_refs:
- request-0032
spec_refs:
- spec-0049
- spec-0050
- spec-0051
- spec-0052
- spec-0053
work_package_refs:
- ref: wp-0020
  seq: 1000
  display: '1'
- ref: wp-0021
  seq: 2000
  display: '2'
- ref: wp-0022
  seq: 3000
  display: '3'
- ref: wp-0023
  seq: 4000
  display: '4'
workflow: strict
standard_refs:
- standard-04
- standard-05
- standard-06
- standard-08
- standard-11
---

# Objectives

- keep stage one generic, modular, and config-driven
- keep current AUDiaGentic product contracts stable unless a migration item says otherwise
- enable future targets, backends, overlays, and variants through registries instead of widened hardcoded branches
- make packetization and later import straightforward

# Work-package split

1. `wp-0020` architecture and boundary freeze
2. `wp-0021` CLI surface and reconcile flow
3. `wp-0022` external targets, backends, overlays, and artifacts
4. `wp-0023` verification, fixtures, and packetization

# Delivery Approach

Stage one is delivered as four sequential work packages. Each package freezes a design slice and produces implementation-ready packet boundaries before the next package begins.

1. `wp-0020` freezes architecture nouns, layering, and registry ownership. No CLI or target work starts until this is complete.
2. `wp-0021` consumes `wp-0020` outputs and freezes the CLI contract and shared resolution flow.
3. `wp-0022` consumes `wp-0020` outputs and freezes target, backend, overlay, and artifact modeling.
4. `wp-0023` consumes all prior outputs and freezes the fixture catalog, regression matrix, and packet boundaries.

Each package produces bounded implementation packets with likely file surfaces, non-goals, and done criteria so a single implementor can own one slice without editing every installer file.

# Dependencies

## Internal

- `request-0032` drives the scope and motivation for all downstream items.
- `spec-0049` through `spec-0053` define the requirements that each work package implements.
- `wp-0020` is a prerequisite for `wp-0021` and `wp-0022`; `wp-0023` depends on all four.

## External

- Current repo CLI entrypoint at `src/audiagentic/channels/cli/main.py`.
- Current lifecycle and config foundations under `src/audiagentic/runtime/lifecycle/` and `src/audiagentic/foundation/config/`.
- Existing `.audiagentic/*.yaml` contracts that must remain readable during stage one.

# Risks

- widening current hardcoded product modules instead of adding installer seams
- conflating internal components, external targets, and realized capabilities
- treating one current target type as if it defines the platform model
- under-specifying verification for compatibility and migration behavior
