---
id: spec-001
label: Archive state and functionality specification
state: done
summary: Define archive state workflow, state-based archive behavior, and filtering
  behavior
request_refs:
- request-004
standard_refs:
- standard-0006
- standard-0005
- standard-0009
task_refs: []
---





# Purpose

Define archive state workflow and functionality for planning items to enable archiving
older or redundant items while maintaining historical records and queryability.

# Scope

- Archive state for all planning item kinds (request, spec, plan, task, wp, standard)
- State-based archive and restore behavior in the planning core
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
   - archived → a valid active state for that item kind, as allowed by the configured workflow
3. Archived items cannot be modified except through allowed state restoration and explicitly-supported archive metadata updates.
4. Archive behavior should remain canonical in workflow/core planning logic; MCP may expose convenience affordances later, but should not define separate archive semantics.

## State-Based Archive Transition

```python
def tm_state(
    id_: str,
    new_state: str,
    reason: str | None = None,
    actor: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Change planning item state, including archive/restore transitions."""
```

Requirements:
- Transition item to `archived` when the requested state is archive
- Record archive metadata (archived_at, archived_by or actor, reason)
- Log archive event
- Return archive result

## State-Based Restore Transition

```python
def tm_state(
    id_: str,
    new_state: str,
    actor: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Change planning item state, including archive/restore transitions."""
```

Requirements:
- Transition item from `archived` back to a valid non-archived state for that item kind
- Record restore metadata (restored_at, restored_by or actor)
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
6. Future workflow triggers may act on archived state later, but this phase only requires the core state semantics and directly related read/validation behavior

# Acceptance Criteria

1. Archived state is defined for all planning kinds
2. State transitions are validated correctly
3. State-driven archive transitions move items to `archived` with metadata
4. State-driven restore transitions move items back to a valid active state with metadata
5. tm_list() excludes archived items by default
6. tm_validate() skips cross-ref validation for archived items
7. tm_show() includes archive metadata
8. Archive events are logged
