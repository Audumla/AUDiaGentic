---
id: task-25
label: Update tm_validate with archive validation rules
state: draft
summary: Add validation for archive metadata, flag cross-references to archived objects
spec_ref: spec-7
---









# Description

Add validation rules for archived objects and flag cross-references to archived objects.

## Archive Metadata Validation

**Rules:**
1. If `is_archived=true`, must have:
   - `archived_at`: ISO 8601 timestamp
   - `archived_by`: Non-empty string
   - `archive_reason`: Non-empty string
2. If `is_archived=false`, archive_metadata can be null or empty
3. If `restored_at` present, must have `restored_to_state` and `restored_by`

**Validation Logic:**
```python
def validate_archive_metadata(obj):
    if obj.archive_metadata.is_archived:
        errors = []
        if not obj.archive_metadata.archived_at:
            errors.append("archived_at required for archived objects")
        if not obj.archive_metadata.archived_by:
            errors.append("archived_by required for archived objects")
        if not obj.archive_metadata.archive_reason:
            errors.append("archive_reason required for archived objects")
        if obj.archive_metadata.restored_at and not obj.archive_metadata.restored_to_state:
            errors.append("restored_to_state required when restored_at present")
        return errors
    return []
```

## Cross-Reference Validation

**Rules:**
1. Active objects should not reference archived objects as dependencies
2. If cross-reference exists, flag as warning (not error)
3. Provide guidance on how to handle archived references

**Validation Logic:**
```python
def validate_cross_references(obj, all_objects):
    warnings = []
    for ref in obj.get_references():
        referenced = all_objects.get(ref.id)
        if referenced and referenced.archive_metadata.is_archived:
            warnings.append({
                "type": "archived_reference",
                "object_id": obj.id,
                "referenced_id": ref.id,
                "message": f"References archived object {ref.id}",
                "suggestion": "Consider updating reference or restoring archived object"
            })
    return warnings
```

## tm_validate Integration

**Updated Behavior:**
1. Run existing validation rules
2. Run archive metadata validation for each object
3. Run cross-reference validation
4. Return combined errors and warnings

**Output Format:**
```json
{
  "errors": [],
  "warnings": [
    {
      "type": "archived_reference",
      "object_id": "task-0001",
      "referenced_id": "plan-0001",
      "message": "References archived object plan-0001",
      "suggestion": "Consider updating reference or restoring archived object"
    }
  ]
}
```

# Acceptance Criteria

1. Archive metadata validation catches missing required fields
2. Cross-reference validation flags references to archived objects
3. Warnings do not block validation (errors do)
4. Validation output includes helpful suggestions
5. Performance impact minimal
6. Backward compatible (existing validation still works)

# Notes

- Cross-reference warnings are informational, not blocking
- Consider adding configuration to make archived references errors
- Archive validation should be fast (indexed fields)
