---
id: spec-0050
label: Generic installer architecture and registry model
state: draft
summary: Define the installer as a generic, config-driven reconciliation platform with registry-owned definitions, explicit layering, and separation between product-owned contracts and installer-platform contracts.
request_refs:
- request-0032
standard_refs:
- standard-0006
- standard-0008
- standard-0011
---

# Purpose

Prevent the installer slice from becoming a config-shaped restatement of current repo files and hardcoded ids.

# Architecture rules

## Layering

- CLI and command parsing are surface concerns
- desired-state resolution and reconciliation orchestration are application concerns
- current-state discovery, filesystem mutation, artifact handling, and backend execution are infrastructure concerns
- installer nouns and compatibility rules are domain concerns

## Core nouns

The model must separate:
- `definition`
- `desired-state`
- `observed-state`
- `realized-capability`
- `plan-step`
- `backend-handler`

## Registry ownership

Installer-facing definitions must be registry-owned for:
- internal components
- external targets
- shared dependencies
- overlays/channels
- variants
- backends
- capability contracts

## Boundary rule

Current repo-owned contracts may remain stable, but they must not become the source of truth for generic installer evolution.

## Resolution ownership

- registry loading belongs in config or registry modules
- desired-state composition belongs in application-layer resolver modules
- compatibility rules belong in domain or contract modules
- observation and mutation belong in backend-specific infrastructure handlers
- CLI and future MCP or other surfaces may call the same application-layer entrypoints

## Minimum registry groups

- `components`
- `targets`
- `dependencies`
- `overlays`
- `backends`
- `variants`
- `capability-contracts`

Each group must support shipped definitions plus room for future additive entries without widening core nouns.

## Likely implementation surfaces

- `src/audiagentic/foundation/config/`
- `src/audiagentic/foundation/contracts/`
- `src/audiagentic/runtime/lifecycle/`
- thin surface hooks under `src/audiagentic/channels/cli/`

## Do not change in this slice

- do not treat `canonical_ids.py` as installer registry source of truth
- do not move product-owned provider/profile concepts wholesale into installer-owned definitions
- do not let backend handlers define domain rules during execution
- do not add import-time self-registration for targets, backends, or overlays

## Verification expectations

- architecture review confirms layer placement for each major installer concern
- at least one non-default definition in each planned registry group is representable without changing core nouns
- test or design evidence shows CLI can call installer application flow without owning resolution logic
- migration notes name current hot spots that remain product-owned versus new installer-owned seams

# Acceptance Criteria

- [ ] layer placement is explicit
- [ ] generic nouns are explicit
- [ ] registry ownership is explicit
- [ ] product versus platform boundary is explicit
- [ ] resolution ownership is explicit
- [ ] likely implementation surfaces are explicit
- [ ] verification expectations are explicit
