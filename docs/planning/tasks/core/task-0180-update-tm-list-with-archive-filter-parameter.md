---
id: task-0180
label: Update tm_list with archive filter parameter
state: done
summary: Add include_archived parameter to tm_list() to filter archived items
spec_ref: spec-001
meta:
  task_refs:
  - ref: wp-0009
    seq: 1002
---



# Description

Add include_archived parameter to tm_list() to filter archived items.

## Requirements

```python
def tm_list(
    kind: str | None = None,
    include_archived: bool = False,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """List planning items with archive filtering.
    
    Args:
        kind: Optional kind filter
        include_archived: Include archived items (default: False)
        root: Optional project root
    
    Returns:
        List of item summaries
    """
```

## Implementation

- Update `tools/planning/tm_helper.py` list surface
- Update `src/audiagentic/planning/app/api.py` list/scan surface as needed
- Filter by state when include_archived=False
- Default behavior: exclude archived items
- Keep query behavior aligned with the canonical state model

## Acceptance Criteria

1. tm_list() excludes archived items by default
2. tm_list(include_archived=True) includes archived items
3. Archive state is included in item metadata
4. Performance is not significantly impacted

# Notes

- Implemented in `tools/planning/tm_helper.py` and exposed through both MCP server entrypoints.
- List results now include archive awareness and exclude archived items unless explicitly requested.
