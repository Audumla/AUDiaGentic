---
id: request-0032
label: Build a generic stage-one installer and CLI platform for AUDiaGentic
state: captured
summary: Extend the existing AUDiaGentic CLI into a generic installer and reconciliation platform that can enable AUDiaGentic in projects, manage optional overlays and external targets through registries and config, preserve richer existing projects, and support artifact-centric delivery and durable regression coverage.
source: codex-external-pack-recut
spec_refs:
- spec-0049
- spec-0050
- spec-0051
- spec-0052
- spec-0053
meta:
  supersedes_external_pack: audiagentic_stage1_planning_pack_v13
---

# Understanding

The repository already has the shared install model, current CLI entrypoint, lifecycle foundations, release foundations, and project-local config surfaces needed for a stage-one installer slice.

The missing planning slice is not "another installer." It is a generic installer platform layered over the current repo that:
- keeps current repo-owned contracts stable where they remain product-owned
- introduces registry-owned installer definitions for targets, backends, overlays, dependencies, and capabilities
- resolves desired state from config and flags rather than from hardcoded object sets
- preserves richer existing projects by default
- keeps clean-project enablement narrow and explicit
- supports artifact-centric operator delivery instead of assuming source checkout

# In Scope

- thin extension of `audiagentic` CLI for install/update/uninstall/status/doctor
- generic installer nouns and registry-owned definitions
- separation of definitions, desired state, observed state, realized capability, and plan steps
- external target and dependency modeling distinct from internal components
- compatibility-aware validation and preservation-aware resolution
- release-artifact and upgrade-verification planning for stage one
- reusable regression and fixture planning

# Out of Scope

- replacing the existing CLI with a second command surface
- rewriting all current repo config/contracts into installer-native shapes
- dynamic plugin runtime loading in stage one
- live network or vendor-dependent verification as a default requirement

# Open Questions

- Which target kinds support `apply` in stage one versus `plan` and `doctor` only?
- How much observed state belongs in installed-state versus diagnostics-only outputs?
- Which artifact forms are mandatory in stage one across Windows, Linux, and macOS?
- Which backend contracts are required now versus reserved for later?
