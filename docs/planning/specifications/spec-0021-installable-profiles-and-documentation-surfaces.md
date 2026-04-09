---
id: spec-0021
label: Installable profiles and documentation surfaces
state: draft
summary: Define installable profile packs, configurable documentation surfaces, request profiles, references docs, and MCP access to project docs without violating the template installation contract.
request_refs:
  - request-0004
task_refs:
  - ref: task-0181
    seq: 1000
  - ref: task-0182
    seq: 2000
  - ref: task-0183
    seq: 3000
  - ref: task-0184
    seq: 4000
  - ref: task-0185
    seq: 5000
  - ref: task-0186
    seq: 6000
  - ref: task-0187
    seq: 7000
  - ref: task-0188
    seq: 8000
standard_refs:
  - standard-0001
  - standard-0002
workflow: standard
---

# Purpose

Define the next additive extension to the planning component so AUDiaGentic can install planning and documentation capability into other projects at different levels of depth.

# Scope

In scope:
- installable profile-pack model for planning/documentation depth
- project documentation surface model
- references docs as a first-class documentation-surface family
- request profiles for feature and issue capture
- supporting-doc metadata and structured sidecar conventions
- central manifest and migration-registry scaffolding
- planning MCP expansion for project docs, support docs, sections, and subsection paths
- documentation-sync obligations for completed work
- validation, testing, and review notes needed before implementation starts

Out of scope:
- installer frontend implementation
- lifecycle/install scripts
- provider execution integration
- runtime/streaming features
- converting this repository into a standalone app instead of a reusable template

# Requirements

1. The planning component must support installable profile packs with defaults for:
   - minimal
   - standard
   - full_project
   - audiagentic_full

2. A profile pack must define:
   - which planning objects are expected
   - which project documentation surfaces exist
   - which standards are active
   - workflow defaults where relevant
   - documentation-sync obligations by work kind

3. The design must not duplicate or blur the existing execution-layer workflow profiles. Planning profile packs, request profiles, and execution workflow profiles must remain distinct concepts.

4. Documentation surfaces must be configurable and optional. They may include:
   - README
   - CHANGELOG
   - canonical docs under `docs/`
   - reference and how-to docs under `docs/references/`

5. Project docs must remain visible and human-editable, with ownership/update policy aligned to the managed-surface contract for template installation.

6. The planning MCP must expose project documentation surfaces and section-level navigation/update operations without hiding the current heading-based implementation limits.

7. Requests remain the canonical issue object, with request profiles used only as classification/default metadata rather than a replacement issue system.

8. Supporting documents must have explicit metadata so they do not become loose notes, and the implementation plan must state whether they are sidecar docs or first-class indexed planning objects.

9. The documentation model must support required and optional sections plus free-form subsections.

10. Documentation-sync obligations for completed tasks/work packages must be explicit and queryable.

11. The implementation must introduce central version-pinning/manifests and migration scaffolding without requiring the installer to exist yet.

12. Any accepted implementation plan must include config wiring, schema validation, repo scanning/indexing impact, and automated test coverage.

# Constraints

- The core planning hierarchy must not change.
- The planning component must remain separate from the execution/job layer.
- The installer/distribution mechanism remains undecided and must not leak into the planning core.
- Profile/config composition must scale without forcing one giant config file.
- The template installation contract in architecture doc 50 remains authoritative for runtime ownership modes and install seeding docs.
- New tracked planning docs must use IDs that do not collide with existing objects in the repository.

# Acceptance Criteria

- profile-pack config model exists and uses non-conflicting naming
- documentation-surface config model exists
- request-profile config model exists for feature and issue, with examples and schema scaffolding
- references docs are modeled with ownership/update guidance
- central manifest and migration-registry scaffolding exist
- planning MCP examples include project-doc, support-doc, section, and subsection operations
- support-doc metadata model exists and its indexing/validation status is explicit
- doc-sync requirements model exists
- required config, schema, validator, and test updates are called out in leaf tasks
- junior-dev-level implementation docs exist for each leaf task in this delta
