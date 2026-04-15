---
id: wp-003
label: MCP and section navigation expansion
state: done
summary: Expand the planning helper and MCP surface for documentation surfaces, references,
  and section navigation while documenting current implementation limits.
plan_ref: plan-0007
task_refs:
- ref: task-0185
  seq: 1000
- ref: task-0186
  seq: 2000
standard_refs:
- standard-0001
- standard-0002
workflow: standard
meta:
  doc_surface_refs:
  - planning_references
  doc_sync_required: true
  doc_sync_status: pending
---







# Objective

Define the API/helper/MCP work needed to expose project documentation surfaces and safer section-level navigation.

# Scope of This Package

- helper and MCP signature alignment
- documentation-surface and references listing
- section and subsection navigation
- explicit treatment of heading-based best-effort behavior

# Inputs

- spec-0021
- plan-003
- current `PlanningAPI.update_content(...)` behavior
- current helper and MCP wrapper files

# Instructions

Prefer small additive helpers over a deep rewrite, but do not describe section-registry behavior as canonical if the underlying API still relies on literal headings.

# Required Outputs

- reviewed helper/MCP additions
- documented section/subsection behavior and limits
- leaf task docs for MCP/helper work
- verification matrix covering helper/MCP smoke paths

# Acceptance Checks

- helper and MCP methods stay signature-compatible
- every new MCP operation maps to a concrete helper/API seam
- docs call out where behavior is advisory or best-effort rather than first-class

# Non-Goals

- rewriting the entire planning API body model
- introducing a separate MCP server for docs
