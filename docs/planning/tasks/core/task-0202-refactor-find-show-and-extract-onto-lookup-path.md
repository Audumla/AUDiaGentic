---
id: task-0202
label: Refactor _find(), show(), and extract() onto lookup path
state: done
summary: Replace scan_items() calls in api._find(), ext_mgr.show(), and ext_mgr.extract()
  with the new lookup(id) resolver to eliminate O(n) full-repo scans for single-item
  reads
spec_ref: spec-007
request_refs: []
standard_refs:
- standard-0005
- standard-0006
---






# Description

Refactor three internal single-item read paths to use `lookup(id)` from task-0201 instead of calling `scan_items()`:

**`api._find(id_)`** — currently iterates all items from `scan_items()` to find one by id. Replace with `self.lookup(id_)`.

**`ext_mgr.ExtractsMgr.show(id_)`** — currently calls `scan_items()`, builds a full dict keyed by id, then returns one entry. Replace with a direct `lookup(id_)` call and return the item's frontmatter.

**`ext_mgr.ExtractsMgr.extract(id_)`** — currently calls `scan_items()` again, then calls `show()` internally (causing a triple scan). Replace with a single `lookup(id_)` call and build the extract result from that.

No changes to the public method signatures. The refactor is internal only.

# Acceptance Criteria

- `_find()`, `show()`, and `extract()` no longer call `scan_items()` for single-item reads
- Behaviour is identical to before for all existing callers
- All existing tests pass without modification
- A test confirms that a single-item `show()` or `extract()` call does not trigger `scan_items()`

# Notes

Depends on task-0200 (lookup.json) and task-0201 (lookup/head helpers). Bulk operations — `validate()`, `index()`, `status()` — still use `scan_items()` and are not in scope here.
