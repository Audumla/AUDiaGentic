---
id: task-172
label: Define supporting-doc metadata and registry behavior
state: done
summary: Review support-doc schema and registry behavior, including whether support
  docs are indexed planning objects or structured sidecar docs
spec_ref: spec-8
---














# Description

Review the supporting-doc proposal so metadata, storage, indexing, and ownership are clear before any code is written.

**Status: IMPLEMENTED**

All implementation work for task-0175 is complete:
- Support docs explicitly treated as structured sidecar docs (not first-class planning kinds)
- SupportingDocsManager reads from docs/planning/supporting/ directory
- Metadata fields: id, label, role, supports, status, owner, used_by
- Allowed roles: analysis, standard, execution_reference, validation, migration, coverage, decision
- Status values: draft, active, superseded
- list_support_docs() supports filtering by supports_id and role
- Schema in supporting-doc.schema.json validates metadata structure
- Support docs are discoverable via helper: list_support_docs()
- Support docs are NOT in planning scan/index/validator kind lists
- Support docs do NOT use planning id counters
- Tests verify support docs are discoverable but not treated as core planning kinds
- Docs in planning-supporting-docs.md and planning-verification-matrix.md document sidecar behavior
- Junior implementer cannot accidentally widen planning-kind model

# Acceptance Criteria

1. The task locks support docs as structured sidecar docs in this phase.
2. The task documents why repo scanning, validation, and indexes are not being widened to include support docs as first-class planning kinds yet.
3. The task documents the allowed roles, ownership, lifecycle, and MCP visibility of support docs.
4. The task includes examples that are sufficient for future smoke testing.

# Notes

- Suitable with revision.
- The pack introduces `supporting-doc.schema.json` and sample files, but current repo scanning and validation only understand request/spec/plan/task/wp/standard objects.
- For this phase, support docs are explicitly treated as structured sidecar docs with metadata and MCP visibility rather than first-class planning kinds.

# Implementation Notes

- Keep support docs sidecar and metadata-driven for this phase.
- Do not widen repo iteration, validators, or indexes to treat support docs as first-class planning kinds during the initial merge.
- State the sidecar rule clearly in the spec, MCP docs, and verification matrix.


# Execution Checklist

Implementation type: support-doc metadata + helper listing + docs + tests.

Files to change:
- `src/audiagentic/planning/app/support_mgr.py`
- `src/audiagentic/contracts/schemas/planning/supporting-doc.schema.json`
- `docs/planning/supporting/support-0001-doc-surfaces-analysis.md`
- `docs/references/planning/planning-supporting-docs.md`
- `docs/references/planning/planning-verification-matrix.md`
- `tests/integration/planning/test_tm_helper_extensions.py`

Steps:
1. Keep support docs as structured sidecar docs only.
2. Define the allowed metadata fields: id, label, role, supports, status, owner, used_by.
3. Ensure support-doc listing reads metadata from `docs/planning/supporting/` and does not require scan/index integration.
4. Add tests proving support docs are discoverable but not treated as core planning kinds.
5. Keep docs explicit that first-class planning-object treatment is deferred.

Do not change:
- planning scan/index/validator kind lists
- id counters for new planning kinds
- request/spec/plan/task/wp/standard schemas to absorb support docs as a new kind

Verification:
- `pytest -q tests/integration/planning/test_tm_helper_extensions.py`
- `python tools/planning/tm.py validate`
- manual check that support docs live only under `docs/planning/supporting/`

Done means:
- sidecar support-doc behavior is clear and test-backed
- a junior implementer cannot accidentally widen the planning-kind model while doing this task
