---
id: spec-0003
label: Archive state workflow specification
state: draft
summary: Define archive state, tm_archive/tm_restore functions, tm_list filtering, and validation rules
request_refs:
- request-0003
task_refs:
- ref: task-0022
  seq: 1000
- ref: task-0023
  seq: 2000
- ref: task-0024
  seq: 3000
- ref: task-0025
  seq: 4000
- ref: task-0026
  seq: 5000
---

# Purpose

Define the archive state workflow for planning objects to enable safe removal of obsolete content while preserving historical records and enabling restoration.

# Scope

- Add `archived` state to planning object state machine
- Implement `tm_archive` and `tm_restore` functions
- Update `tm_list` with archive filtering
- Update `tm_next_tasks` to exclude archived objects
- Update `tm_validate` with archive validation rules
- Update `tm_show` to include archive metadata

# Requirements

## State Machine

### Valid States

| State | Description |
|-------|-------------|
| `draft` | Object is being created/edited |
| `ready` | Object is ready for work |
| `in_progress` | Work is actively being done |
| `done` | Work is complete |
| `archived` | Object is obsolete but preserved for history |

### State Transitions

```
draft -> ready -> in_progress -> done -> archived
   |                           ^
   +----------- archived <------+
```

**Rules:**
- Objects can only be archived from `done` state
- Archived objects can be restored to `draft`, `ready`, or `in_progress` states
- Archive operation preserves all object metadata and relationships
- Archived objects are excluded from `tm_next_tasks` and `tm_next_items` queries

## tm_archive Function

**Signature:**
```
tm_archive(id: string, reason: string, archived_by: string) -> archived_object
```

**Parameters:**
- `id`: Object ID to archive
- `reason`: Why the object is being archived
- `archived_by`: User/system performing the archive

**Behavior:**
1. Validates object is in `done` state
2. Sets state to `archived`
3. Records archive metadata (timestamp, reason, actor)
4. Preserves all relationships
5. Excludes from active queries

**Error Conditions:**
- Object not in `done` state
- Object ID not found
- Missing required parameters

## tm_restore Function

**Signature:**
```
tm_restore(id: string, restored_to_state: string, restored_by: string) -> restored_object
```

**Parameters:**
- `id`: Archived object ID
- `restored_to_state`: State to restore to (draft/ready/in_progress)
- `restored_by`: User/system performing restoration

**Behavior:**
1. Validates object is in `archived` state
2. Transitions to specified state
3. Removes archive metadata
4. Re-includes in active queries

**Error Conditions:**
- Object not in `archived` state
- Invalid restored_to_state value
- Object ID not found

## tm_list with Archive Filter

**Signature:**
```
tm_list(kind: string, include_archived: boolean)
```

**Parameters:**
- `kind`: Object type (plan/request/spec/task/wp)
- `include_archived`: Include archived objects in results (default: false)

**Behavior:**
- When `include_archived=false` (default): Only returns active objects
- When `include_archived=true`: Returns all objects including archived

## tm_next_tasks with Archive Exclusion

**Signature:**
```
tm_next_tasks(state: string, domain: string)
```

**Behavior:**
- Automatically excludes archived objects from results
- Only returns objects in active states (draft, ready, in_progress)

## tm_validate with Archive Rules

**Validation Rules:**
- Archived objects must have valid archive metadata
- Archived objects cannot be referenced as active dependencies
- Cross-references to archived objects should be flagged in validation output

# Constraints

- Archive state is additive; existing states remain unchanged
- All existing planning objects must support archive metadata
- Backward compatibility: objects without archive metadata treated as not archived

# Acceptance Criteria

1. `tm_archive` successfully archives objects in `done` state
2. `tm_restore` successfully restores archived objects to active states
3. `tm_list` with `include_archived=false` excludes archived objects
4. `tm_list` with `include_archived=true` includes archived objects
5. `tm_next_tasks` excludes archived objects automatically
6. `tm_validate` flags cross-references to archived objects
7. `tm_show` displays archive metadata for archived objects
8. All state transitions validated correctly
9. Archive metadata preserved through all operations

# Data Model Changes

Add to all planning objects:
```yaml
archive_metadata:
  is_archived: boolean
  archived_at: timestamp
  archived_by: string
  archive_reason: string
  restored_at: timestamp (nullable)
  restored_to_state: string (nullable)
```
