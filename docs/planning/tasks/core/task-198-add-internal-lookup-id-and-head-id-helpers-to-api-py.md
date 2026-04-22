---
id: task-198
label: Add internal lookup(id) and head(id) helpers to api.py
state: done
summary: Add lookup(id) that reads lookup.json and parses only the target markdown
  file, and head(id) that returns index-only metadata without parsing any planning
  doc
spec_ref: spec-10
request_refs: []
standard_refs:
- standard-5
- standard-6
---












# Description

Add two internal helper methods to `src/audiagentic/planning/app/api.py`:

**`lookup(id_: str) -> ItemView`**

- Read `.audiagentic/planning/indexes/lookup.json`
- Resolve the item's path from the index entry
- Call `parse_markdown(path)` on that single file
- Return an `ItemView` equivalent to what `_find()` returns today
- Raise `KeyError` (or a clear `ValueError`) if the id is not in the index

**`head(id_: str) -> dict`**

- Read `.audiagentic/planning/indexes/lookup.json`
- Return the index entry directly: `{id, kind, label, state, path, deleted}`
- No markdown file parse — index data only

Both methods must be available internally for use by `_find()`, `show()`, `extract()`, and any other single-item read path.

# Acceptance Criteria

- `lookup(id)` returns a fully parsed item for a known id without calling `scan_items()`
- `head(id)` returns the index entry dict without opening any markdown file
- Both raise a clear error for an unknown id
- Both are covered by unit tests using a fixture lookup.json

# Notes

Depends on task-0200 (lookup.json must exist before these helpers can be used). These helpers are internal — not part of the public tm_helper or MCP surface yet (that is task-0204).
