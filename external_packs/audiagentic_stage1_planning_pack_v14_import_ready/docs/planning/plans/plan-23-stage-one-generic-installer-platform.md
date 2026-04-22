---
id: plan-23
label: Deliver a modular stage-one generic installer platform
state: draft
summary: Deliver the stage-one installer slice as four modular work packages covering architecture, CLI and reconcile flow, target/backend/artifact modeling, and regression foundations, while preserving current repo-owned contracts and enabling future extensibility through config and registries.
request_refs:
- request-32
spec_refs:
- spec-80
- spec-81
- spec-82
- spec-83
- spec-84
- spec-85
work_package_refs:
- ref: wp-28
  seq: 1000
  display: '1'
- ref: wp-29
  seq: 2000
  display: '2'
- ref: wp-30
  seq: 3000
  display: '3'
- ref: wp-31
  seq: 4000
  display: '4'
workflow: strict
standard_refs:
- standard-4
- standard-5
- standard-6
- standard-8
- standard-11
---

# Objectives

- keep stage one generic, modular, and config-driven
- keep current AUDiaGentic product contracts stable unless a migration item says otherwise
- enable future targets, backends, overlays, and variants through registries instead of widened hardcoded branches
- make packetization and later import straightforward

# Work-package split

1. `wp-28` architecture and boundary freeze
2. `wp-29` CLI surface and reconcile flow
3. `wp-30` external targets, backends, overlays, and artifacts
4. `wp-31` verification, fixtures, and packetization

# Delivery Approach

Stage one is delivered as four sequential work packages. Each package freezes a design slice and produces implementation-ready packet boundaries before the next package begins.

1. `wp-28` freezes architecture nouns, layering, and registry ownership. No CLI or target work starts until this is complete.
2. `wp-29` consumes `wp-28` outputs and freezes the CLI contract and shared resolution flow.
3. `wp-30` consumes `wp-28` outputs and freezes target, backend, overlay, and artifact modeling.
4. `wp-31` consumes all prior outputs and freezes the fixture catalog, regression matrix, and packet boundaries.

Each package produces bounded implementation packets with likely file surfaces, non-goals, and done criteria so a single implementor can own one slice without editing every installer file.

# Dependencies

## Internal

- `request-32` drives the scope and motivation for all downstream items.
- `spec-80` through `spec-85` define the requirements that each work package implements.
- `wp-28` is a prerequisite for `wp-29` and `wp-30`; `wp-31` depends on all four.

## External

- Current repo CLI entrypoint at `src/audiagentic/channels/cli/main.py`.
- Current lifecycle and config foundations under `src/audiagentic/runtime/lifecycle/` and `src/audiagentic/foundation/config/`.
- Existing `.audiagentic/*.yaml` contracts that must remain readable during stage one.

# Risks

- widening current hardcoded product modules instead of adding installer seams
- conflating internal components, external targets, and realized capabilities
- treating one current target type as if it defines the platform model
- under-specifying verification for compatibility and migration behavior
