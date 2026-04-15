---
id: task-0020
label: Update tm_show to include archive metadata
state: draft
summary: Add archive_metadata field to tm_show output showing is_archived, archived_at,
  archived_by, archive_reason
spec_ref: spec-004
---



# Description

Update `tm_show` to display archive metadata for archived objects.

## Current tm_show Output

```json
{
  "id": "task-0001",
  "kind": "task",
  "label": "Analyze existing docs structure",
  "state": "done",
  "summary": "Analyze existing docs structure",
  "path": "docs/planning/tasks/task-0001.md"
}
```

## Updated tm_show Output (Active Object)

No change for active objects:

```json
{
  "id": "task-0001",
  "kind": "task",
  "label": "Analyze existing docs structure",
  "state": "done",
  "summary": "Analyze existing docs structure",
  "path": "docs/planning/tasks/task-0001.md"
}
```

## Updated tm_show Output (Archived Object)

Add archive_metadata field:

```json
{
  "id": "plan-0001",
  "kind": "plan",
  "label": "Pilot migration plan - implementation docs",
  "state": "done",
  "summary": "Migrate docs/implementation folder to new planning structure as proof of concept",
  "path": "docs/planning/plans/plan-0001.md",
  "archive_metadata": {
    "is_archived": true,
    "archived_at": "2026-04-07T12:00:00Z",
    "archived_by": "user@example.com",
    "archive_reason": "Replaced by plan-0004 - Pilot migration test, do not use",
    "restored_at": null,
    "restored_to_state": null,
    "restored_by": null
  }
}
```

## Implementation

**tm_show Function:**
```python
def tm_show(id: str):
    obj = get_object_by_id(id)
    result = {
        "id": obj.id,
        "kind": obj.kind,
        "label": obj.label,
        "state": obj.state,
        "summary": obj.summary,
        "path": obj.path
    }
    
    # Add archive_metadata if object is archived
    if obj.archive_metadata and obj.archive_metadata.is_archived:
        result["archive_metadata"] = {
            "is_archived": True,
            "archived_at": obj.archive_metadata.archived_at,
            "archived_by": obj.archive_metadata.archived_by,
            "archive_reason": obj.archive_metadata.archive_reason,
            "restored_at": obj.archive_metadata.restored_at,
            "restored_to_state": obj.archive_metadata.restored_to_state,
            "restored_by": obj.archive_metadata.restored_by
        }
    
    return result
```

## Display Considerations

### CLI Output
When displaying archived objects in CLI, add visual indicator:

```
[ARCHIVED] plan-0001: Pilot migration plan - implementation docs
  Archived: 2026-04-07 by user@example.com
  Reason: Replaced by plan-0004
```

### API Response
Include archive_metadata in all responses for archived objects.

# Acceptance Criteria

1. `tm_show` includes archive_metadata for archived objects
2. `tm_show` excludes archive_metadata for active objects
3. All archive metadata fields present when archived
4. Null values handled correctly for restoration fields
5. Timestamps in ISO 8601 format
6. Backward compatible (active objects unchanged)

# Notes

- Consider adding `show_archive_metadata` parameter for explicit control
- CLI should provide clear visual distinction for archived objects
- API documentation should explain archive_metadata field
