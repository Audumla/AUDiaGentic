---
id: spec-0052
label: Target, backend, overlay, and artifact model
state: draft
summary: Define how internal components, external targets, overlays, installer backends, dependency scope, and release artifacts are modeled without collapsing them into one namespace or one execution path.
request_refs:
- request-0032
standard_refs:
- standard-0006
- standard-0008
- standard-0011
---

# Purpose

Keep extensibility real by separating target classes and execution backends from current AUDiaGentic-only components.

# Requirements

- internal components remain distinct from external targets and realized capabilities
- overlays such as VS Code remain optional layers, not product center
- target kinds and backend kinds are separate axes
- backend compatibility must consider OS family, target kind, and artifact form
- artifact-centric delivery must be planned as a first-class operator path while preserving source-based development workflows

# Stage-one minimum seams

- target definitions
- dependency definitions
- overlay definitions
- backend definitions
- artifact definitions
- compatibility matrix inputs

## Minimum modeling rules

- internal component ids must remain product-owned and must not double as external target ids
- external targets must declare target kind, backend kind, supported modes, and compatibility inputs
- dependencies must be referenceable independently of targets so shared prerequisites do not get duplicated per target
- overlays must be additive and removable without redefining base project enablement
- realized capabilities must be recorded as outcomes, not configured as if they were definitions
- artifact definitions must distinguish source-dev flows from operator-delivery flows

## Stage-one target examples to preserve genericity

- project enablement target
- optional editor overlay target
- external configured target
- artifact-delivered target
- dependency-only validation target

These are modeling examples, not a fixed exhaustive runtime list.

## Likely implementation surfaces

- registry definitions under `.audiagentic/`-owned config or shipped package config
- compatibility helpers under `src/audiagentic/foundation/contracts/`
- backend dispatch and observation hooks under `src/audiagentic/runtime/lifecycle/` and release-adjacent modules
- release packaging surfaces under `src/audiagentic/release/`

## Do not change in this slice

- do not force VS Code or any single current overlay to define target model semantics
- do not blur dependency validation with target realization
- do not assume one backend can satisfy all target kinds
- do not treat artifact packaging as an afterthought outside installer planning

## Verification expectations

- target-kind versus backend-kind compatibility matrix examples
- artifact-form cases across Windows, Linux, and macOS expectations
- at least one case showing overlay-on-base-project behavior
- at least one case showing dependency validation without full target apply
- case proving realized capability records stay distinct from configured components and targets

# Acceptance Criteria

- [ ] namespace separation is explicit
- [ ] target-versus-backend distinction is explicit
- [ ] overlay model is explicit
- [ ] artifact model is explicit
- [ ] minimum modeling rules are explicit
- [ ] likely implementation surfaces are explicit
- [ ] verification expectations are explicit
