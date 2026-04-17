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
standard_refs:
- standard-0004
- standard-0005
- standard-0006
- standard-0008
- standard-0011
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

# Risks

- widening current hardcoded product modules instead of adding installer seams
- conflating internal components, external targets, and realized capabilities
- treating one current target type as if it defines the platform model
- under-specifying verification for compatibility and migration behavior
