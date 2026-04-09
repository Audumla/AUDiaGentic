---
id: spec-0023
label: Archive state and functionality specification
state: draft
summary: Define archive state workflow, tm_archive/tm_restore functions, and filtering
  behavior
request_refs:
- request-0005
task_refs: []
---

# Purpose

Define archive state workflow and functionality for planning items to enable archiving
older or redundant items while maintaining historical records and queryability.

# Scope

- Archive state for all planning item kinds (request, spec, plan, task, wp, standard)
- tm_archive() and tm_restore() helper functions
- Archive filtering in tm_list()
- Archive validation rules in tm_validate()
- Archive metadata in tm_show()

# Requirements

## State Machine

1. Add "archived" state to all planning item kinds
2. Define valid transitions:
   - draft → archived
   - ready → archived
   - in_progress → archived
   - done → archived
   - archived → ready (restore)
3. Archived items cannot be modified (state transitions rejected except restore)

## tm_archive()

```python
def tm_archive(
    id_: str,
    reason: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Archive a planning item."""
```

Requirements:
- Transition item to archived state
- Record archive metadata (archived_at, archived_by, reason)
- Log archive event
- Return archive result

## tm_restore()

```python
def tm_restore(
    id_: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Restore an archived planning item."""
```

Requirements:
- Transition item back to ready state
- Record restore metadata (restored_at, restored_by)
- Log restore event
- Return restore result

## tm_list()

```python
def tm_list(
    kind: str | None = None,
    include_archived: bool = False,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """List planning items with archive filtering."""
```

Requirements:
- Exclude archived items by default (include_archived=False)
- Include archived items when requested (include_archived=True)
- Archive state included in item metadata

## tm_validate()

Requirements:
- Archived items skip cross-reference validation
- Archived items still validate required fields
- Report archived items separately in validation output

## tm_show()

Requirements:
- Include archive metadata for archived items
- Include restore metadata for restored items
- Show None for archive fields on non-archived items

# Constraints

1. Archive metadata stored in YAML frontmatter
2. Archive events logged to events.jsonl
3. Archived items remain queryable
4. No automatic archive policies (manual archive only)
5. No bulk archive operations in this phase

# Acceptance Criteria

1. Archived state is defined for all planning kinds
2. State transitions are validated correctly
3. tm_archive() transitions item to archived state with metadata
4. tm_restore() transitions item back to ready state with metadata
5. tm_list() excludes archived items by default
6. tm_validate() skips cross-ref validation for archived items
7. tm_show() includes archive metadata
8. Archive events are logged
