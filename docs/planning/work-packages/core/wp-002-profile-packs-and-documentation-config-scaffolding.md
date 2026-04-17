---
id: wp-002
label: Profile packs and documentation config scaffolding
state: done
summary: Define profile-pack, documentation-surface, request-profile, and manifest
  scaffolding with template-safe ownership rules and validation impacts called out.
plan_ref: plan-0007
task_refs:
- ref: task-0181
  seq: 1000
- ref: task-0182
  seq: 2000
- ref: task-0183
  seq: 3000
- ref: task-0184
  seq: 4000
standard_refs:
- standard-0001
- standard-0002
workflow: standard
meta:
  doc_surface_refs:
  - readme
  - changelog
  - planning_references
  doc_sync_required: true
  doc_sync_status: pending
---







# Objective

Prepare the configuration and documentation scaffolding for profile packs and documentation surfaces without yet implementing the runtime behavior.

# Scope of This Package

- documentation-surface config and schema
- profile-pack and request-profile structure
- references docs guidance
- manifest and migration-registry scaffolding
- template-installation ownership and update-policy alignment

# Inputs

- request-3
- spec-0021
- architecture docs 12 and 50
- current planning config split under `.audiagentic/planning/config/`

# Instructions

Keep this package additive. Do not introduce new planning concepts that duplicate execution workflow profiles or imply installer behavior that does not exist yet.

# Required Outputs

- reviewed config shape for documentation surfaces
- reviewed profile-pack shape and naming guidance
- reviewed request-profile placement and default semantics
- reviewed manifest/migration scaffolding notes
- updated implementation docs for the four leaf tasks

# Acceptance Checks

- config changes identify every existing file/class/schema that must be updated
- naming avoids collisions with workflow profiles already defined in the repo
- documentation-surface ownership rules align to the managed-surface contract
- manifest/migration work is scoped as scaffolding rather than hidden installer work

# Non-Goals

- implementing install scripts
- changing execution/job workflow profiles
- converting project docs into opaque generated output
