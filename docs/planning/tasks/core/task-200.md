---
id: task-200
label: Add lookup.json global index generation to idx_mgr
state: done
summary: Extend idx_mgr.py to generate .audiagentic/planning/indexes/lookup.json keyed
  by id with id, kind, path, label, state, and deleted fields alongside existing per-kind
  indexes
spec_ref: spec-7
request_refs: []
standard_refs:
- standard-5
- standard-6
---





# Description

Extend `src/audiagentic/planning/app/idx_mgr.py` to generate a global lookup index at `.audiagentic/planning/indexes/lookup.json` as part of the existing `write_indexes()` call.

The index must be a flat JSON object keyed by planning item id. Each entry must contain:

```json
{
  "spec-007": {
    "id": "spec-007",
    "kind": "spec",
    "label": "...",
    "state": "draft",
    "path": "docs/planning/specifications/spec-007-...",
    "deleted": false
  }
}
```

All planning kinds must be included: requests, specifications, tasks, plans, work-packages, standards. The `deleted` field should be `false` when absent from the source document. Paths should use forward slashes and be relative to the project root.

# Acceptance Criteria

- Running `tm.py index` produces `.audiagentic/planning/indexes/lookup.json`
- All planning items across all kinds appear in the index
- Each entry contains `id`, `kind`, `label`, `state`, `path`, and `deleted`
- Deleted items are included with `deleted: true` so lookup can surface them without a scan
- Re-running `index` overwrites the file cleanly with current state
- Existing per-kind index files are unchanged

# Notes

The lookup index is an accelerator, not the source of truth. It is always regenerated from the markdown files, never edited directly.
