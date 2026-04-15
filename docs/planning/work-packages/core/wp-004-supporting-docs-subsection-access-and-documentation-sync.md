---
id: wp-004
label: Supporting docs, subsection access, and documentation sync
state: done
summary: Extend the planning delta with supporting-doc metadata, subsection-aware
  MCP access, and explicit documentation-sync rules while clarifying current indexing
  and validation limits.
plan_ref: plan-0007
task_refs:
- ref: task-0187
  seq: 1000
- ref: task-0188
  seq: 2000
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

Add explicit supporting-doc sidecar conventions and documentation-sync support without changing the core planning hierarchy.

# Scope of This Package

- supporting-doc metadata and registry
- supporting-doc indexing/validation decision
- documentation sync requirement queries
- verification coverage expectations

# Inputs

- spec-0021
- plan-003
- current MCP server and helper
- current repo scan and validator behavior

# Instructions

Keep the MCP/API compact and high-value. Prefer additive helpers and schemas over large structural changes, and do not claim first-class support-doc behavior unless the pack also scopes the repo/index/validator work required.

# Required Outputs

- support-doc schema and sample docs
- review notes locking support docs as sidecar docs for this phase
- references docs updates
- test and validation checklist

# Acceptance Checks

- support docs are modeled as structured sidecar docs and are discoverable
- support-doc indexing status is explicit
- doc-sync requirements are queryable
- feature list and review notes reflect the additions

# Non-Goals

- no separate support-doc MCP
- no full implementation of project-doc workflow state
