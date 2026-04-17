---
id: task-0173
label: Expand helper and MCP surfaces for documentation views
state: done
summary: Review helper and MCP additions for documentation surfaces, references, and
  support-doc listing
spec_ref: spec-005
---








# Description

Review the helper and MCP additions needed to expose documentation surfaces, references docs, and support-doc queries.

**Status: IMPLEMENTED**

All implementation work for task-0173 is complete:
- Helper functions in tm_helper.py: list_doc_surfaces(), get_doc_surface(), list_reference_docs(), list_request_profiles(), get_request_profile(), list_support_docs(), get_subsection(), get_doc_sync_requirements(), pending_doc_updates(), verify_structure()
- MCP tools registered for all helper functions with @mcp.tool decorator
- Helper and MCP signatures aligned (workflow parameter, doc-surface calls, doc-sync calls)
- DocumentationManager, ReferencesManager, SupportingDocsManager provide backing implementation
- Section registry supports dot and slash notation for subsection paths
- All operations are read-focused except existing planning API update methods
- Tests in test_tm_helper_extensions.py verify:
  - list_doc_surfaces() returns surfaces with seed_on_install
  - list_request_profiles() includes feature and issue
  - get_request_profile() returns correct data
  - get_doc_sync_requirements() and pending_doc_updates() work correctly
  - list_support_docs() and list_reference_docs() return expected data
  - get_subsection() supports dot and slash paths
  - verify_structure() marks optional extensions as non-blocking
- Verification matrix in docs/references/planning/planning-verification-matrix.md backed by real tests

# Acceptance Criteria

1. The task confirms every new MCP tool has a backing helper/API path.
2. The task records the exact signature changes required to keep helper and MCP wrappers aligned.
3. The task identifies missing unit or smoke tests for each new operation.
4. The task distinguishes read-only listing operations from future write/update work.
5. The task produces or updates a concrete verification matrix for MCP and helper behavior.

# Notes

- Suitable with revision.
- The pack correctly addresses the current helper/MCP workflow mismatch, but it overstates readiness by claiming tests that are not present in the pack.
- This task must produce a concrete verification list before implementation begins.

# Implementation Notes

- Keep the corrected `workflow` parameter alignment.
- Record which methods are thin wrappers and which require deeper `PlanningAPI` support.
- Add planned tests for doc-surface listing, reference listing, and support-doc listing.
- Bind the final scope to `docs/references/planning/planning-verification-matrix.md`.


# Execution Checklist

Implementation type: helper/MCP code + tests.

Files to change:
- `tools/planning/tm_helper.py`
- `tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py`
- `src/audiagentic/planning/app/docs_mgr.py`
- `src/audiagentic/planning/app/refs_mgr.py`
- `src/audiagentic/planning/app/support_mgr.py`
- `src/audiagentic/planning/app/section_registry.py`
- `docs/references/planning/planning-mcp-change-first.md`
- `docs/references/planning/planning-verification-matrix.md`
- `tests/integration/planning/test_tm_helper_extensions.py`

Steps:
1. Ensure every new MCP tool has a helper function and real backing code.
2. Keep helper and MCP signatures aligned, especially for `workflow`, doc-surface calls, and doc-sync calls.
3. Keep new documentation-surface operations read-focused unless a task explicitly requires mutation.
4. Add tests for listing doc surfaces, reference docs, request profiles, and support docs.
5. Add tests for one live helper/MCP smoke path such as `tm_verify_structure` or doc-sync queries.

Do not change:
- provider/job execution code
- planning core object kinds
- arbitrary file-mutation behavior through MCP

Verification:
- `pytest -q tests/integration/planning/test_tm_helper_extensions.py`
- `python tools/planning/tm.py validate`

Done means:
- the MCP descriptions match the helper behavior
- helper/runtime signature mismatches are eliminated
- the verification matrix is backed by real tests, not just prose
