---
id: task-358
label: Freeze modular packetization outputs
state: draft
summary: Define packet boundaries, likely file surfaces, and handoff expectations aligned to the four work packages.
spec_ref: spec-84
request_refs:
- request-32
standard_refs:
- standard-4
- standard-6
---

# Description

Make later implementation intake modular instead of one monolithic installer packet.

# Inputs

Read before starting:
- `docs/installer/regression-matrix.md` (output from task-357)
- `docs/installer/fixture-catalog.md` (output from task-356)
- `docs/installer/apply-boundaries.md` (output from task-355)
- `docs/installer/backend-overlay-artifact-contracts.md` (output from task-354)
- `docs/installer/namespace-separation.md` (output from task-353)
- `docs/installer/validation-categories.md` (output from task-352)
- `docs/installer/resolution-reconcile-contract.md` (output from task-351)
- `docs/installer/cli-command-contract.md` (output from task-350)
- `docs/installer/registry-ownership-matrix.md` (output from task-349)
- `docs/installer/noun-layer-assignment.md` (output from task-348)
- `docs/installer/current-state-inventory.md` (output from task-347)
- `wp-28` — architecture and boundaries scope
- `wp-29` — CLI and reconcile scope
- `wp-30` — targets, backends, and artifacts scope
- `wp-31` — verification and packetization scope
- `spec-84` — packetization spec

# Output

Produce `docs/installer/packetization-plan.md` with these sections:

## Packet definitions

For each packet, document:
- Packet name (exact identifier)
- Which WP it maps to (wp-28, wp-29, wp-30, or wp-31)
- Packet scope (what is included, what is excluded)
- Likely file surfaces (exact file paths or directories)
- Explicit non-goals (what this packet does NOT cover)
- Handoff expectations (what the implementor receives, what they produce)
- Dependencies on other packets (which packets must complete first)

## Packet boundaries

Document the boundaries between packets:
- Packet 1 (architecture): what it delivers, what it hands off
- Packet 2 (CLI): what it delivers, what it hands off
- Packet 3 (targets): what it delivers, what it hands off
- Packet 4 (verification): what it delivers, what it hands off

## Handoff protocol

Document how handoffs work:
- What documentation the implementor receives before starting
- What documentation the implementor produces at completion
- How the reviewer verifies the handoff is complete
- What happens if a packet is incomplete (rollback procedure)

# What not to change

- do not merge packets into a single monolithic packet
- do not change the four-WP mapping (each packet maps to exactly one WP)
- do not add packets beyond the four listed (architecture, CLI, targets, verification)
- do not change the packet dependency order (architecture → CLI → targets → verification)
- do not modify existing file surfaces beyond what is listed in Likely surfaces
- do not introduce new file surfaces outside the listed directories
- do not change the handoff protocol once defined

# Blocker handling

- if any upstream task output is missing, record it as a packetization blocker and stop short of inventing the missing dependency
- if WP scope or spec scope changed since this external pack was written, cite the ID and describe the drift rather than relying on stale file paths

# Acceptance criteria

- [ ] all four packets are defined with exact names, scopes, and file surfaces
- [ ] each packet has explicit non-goals (what it does NOT cover)
- [ ] each packet has handoff expectations (what implementor receives and produces)
- [ ] packet dependencies are explicit (which packets must complete first)
- [ ] a packet author can take one slice without reopening whole-pack design
- [ ] architecture, CLI, target modeling, and regression remain separable
- [ ] reviewer can verify by checking that each packet's file surfaces match the directories listed in the packet definitions
