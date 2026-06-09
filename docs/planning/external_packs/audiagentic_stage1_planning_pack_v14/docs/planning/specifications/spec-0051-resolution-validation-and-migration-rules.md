---
id: spec-0051
label: Resolution, validation, preservation, and migration rules
state: draft
summary: Define desired-state resolution order, registry-discovered validation, compatibility categories, preservation defaults, and backward-compatible migration rules for installer-facing config.
request_refs:
- request-0032
standard_refs:
- standard-05
- standard-06
- standard-07
- standard-11
---

# Purpose

Make generic installer behavior safe without tying validation to fixed installer object sets.

# Discovery requirement

Before freezing resolution and validation rules, survey the current lifecycle and validation surfaces to determine:
- where current config normalization happens
- where current validation happens
- what current installed-state semantics exist
- what backward-compatibility assumptions the live repo already depends on

If live behavior conflicts with this spec, document the conflict explicitly instead of inventing a silent merge.

# Scope

This spec defines desired-state resolution order, registry-discovered validation, compatibility categories, preservation defaults, and backward-compatible migration rules for installer-facing config. It covers the shared contract used by `install`, `update`, `status`, `doctor`, and `validate` commands.

# Constraints

- Must not collapse all validation failures into generic `invalid-config` errors.
- Must not require fully migrated config before `plan` or `doctor` can run.
- Must not make compatibility checks backend-blind or OS-blind.
- Must not store every observed fact in installed-state by default.
- Current `.audiagentic/project.yaml`, `.audiagentic/components.yaml`, `.audiagentic/providers.yaml`, and installed-state remain readable during stage one.

# Requirements

## Resolution order

Desired state must resolve from:
1. shipped defaults
2. current project config
3. target config
4. CLI flags
5. preservation policy
6. compatibility rules

## Validation categories

Installer-facing validation must distinguish:
- malformed shape
- unknown reference
- known but unavailable
- unsupported on this backend or OS family
- unsupported in this profile or release
- preservation conflict

## Preservation defaults

- richer existing projects are preserved by default
- clean-project seed behavior must be narrow and explicit
- current `.audiagentic/project.yaml`, `.audiagentic/components.yaml`, `.audiagentic/providers.yaml`, and installed-state semantics remain compatible unless an explicit migration task changes them

## Extension seam

Installer schemas must reserve extension space such as `extensions` or `x-*` for target-specific and backend-specific metadata.

## Shared contract rule

- `install`, `update`, `status`, `doctor`, and `validate` must use the same resolution inputs and compatibility model
- mode changes may alter mutation and reporting behavior, but not the meaning of desired-state resolution

## Backward-compatibility boundary

- current `.audiagentic/project.yaml`, `.audiagentic/components.yaml`, `.audiagentic/providers.yaml`, and installed-state remain readable during stage one
- new installer-facing config may be introduced alongside them, but should be normalized rather than treated as a replacement requirement
- migration rules must define how missing new installer config degrades safely

## Likely implementation surfaces

- registry-aware validators under `src/audiagentic/foundation/contracts/` or `src/audiagentic/foundation/config/`
- normalization or resolver helpers under `src/audiagentic/runtime/lifecycle/`
- CLI and diagnostic surfaces consuming shared results rather than bespoke validation paths

## Do not change in this slice

- do not collapse all validation failures into generic invalid-config errors
- do not require fully migrated config before plan or doctor can run
- do not make compatibility checks backend-blind or OS-blind
- do not store every observed fact in installed-state by default

## Verification expectations

- tests or explicit cases for each validation category
- preservation tests for richer existing project shape versus narrow clean seed
- backward-compatibility case where old config works without new installer config
- extension-field case proving validation can preserve unknown extension payloads while still enforcing base contract
- consistency check proving `doctor` and `validate` use same underlying compatibility results

# Acceptance Criteria

- [ ] resolution order is explicit
- [ ] validation categories are explicit
- [ ] preservation behavior is explicit
- [ ] migration boundary is explicit
- [ ] shared contract rule is explicit
- [ ] likely implementation surfaces are explicit
- [ ] verification expectations are explicit
