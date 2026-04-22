---
id: task-200
label: Add include_body and write_to_disk controls to extract()
state: done
summary: Add explicit include_body and write_to_disk parameters to extract() so callers
  can obtain metadata without body content and without writing to .audiagentic/planning/extracts/{id}.json
spec_ref: spec-10
request_refs: []
standard_refs:
- standard-5
- standard-6
---












# Description

Add two explicit controls to `ext_mgr.ExtractsMgr.extract()`:

**`include_body: bool = True`** — when `False`, return only frontmatter metadata without reading or returning the markdown body. Default `True` preserves current behaviour.

**`write_to_disk: bool = True`** — when `False`, return the extract result without writing to `.audiagentic/planning/extracts/{id}.json`. Default `True` preserves current behaviour.

Update the method signature:

```python
def extract(self, id_: str, with_related: bool = False, with_resources: bool = False,
            include_body: bool = True, write_to_disk: bool = True) -> dict:
```

# Acceptance Criteria

- `extract(id, include_body=False)` returns frontmatter metadata only, no body content
- `extract(id, write_to_disk=False)` returns the result without writing to the extracts directory
- Default behaviour (both `True`) is identical to current behaviour
- All existing callers continue to work without changes
- Tests cover `include_body=False` and `write_to_disk=False` paths

# Notes

Depends on task-0202 (extract already uses lookup path). The `with_related` and `with_resources` parameters already default to `False` and are not changed by this task.
