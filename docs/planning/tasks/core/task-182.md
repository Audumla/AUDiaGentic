---
id: task-182
label: Update tm_show to include archive metadata
state: done
summary: Add archive metadata (archived_at, archived_by, reason) to tm_show() output
spec_ref: spec-1
meta:
  task_refs:
  - ref: wp-0009
    seq: 1004
---



# Description

Add archive metadata (archived_at, archived_by, reason) to tm_show() output.

## Requirements

Archive metadata should be included in item metadata:

```python
{
    "id": "task-0001",
    "kind": "task",
    "label": "Example task",
    "state": "archived",
    "archived_at": "2026-04-09T12:00:00Z",
    "archived_by": "user@example.com",
    "archive_reason": "Feature deprecated",
    "restored_at": None,
    "restored_by": None,
}
```

## Implementation

- Update `src/audiagentic/planning/app/api.py` extracts.show()
- Add archive metadata to item data
- Store metadata in YAML frontmatter
- Include in tm_show() output
- Keep metadata shape aligned with the state-driven archive/restore model

## Acceptance Criteria

1. Archived items show archive metadata in tm_show()
2. Metadata includes timestamp, user, and reason
3. Restored items show restore metadata
4. Non-archived items show None for archive fields

# Notes

- Implemented in `src/audiagentic/planning/app/ext_mgr.py` and validated through helper/API integration tests.
- `tm_show()` now returns stable archive-related fields for both archived and non-archived items.
