---
id: spec-002
label: Planning module improvements implementation specification
state: done
summary: Detailed implementation specification for relation-schema verification, soft
  delete, hard-delete counter safety, bidirectional request traceability, duplicate
  guards, validation feedback, and regression coverage
request_refs:
- request-6
task_refs: []
---


# Purpose

Define implementation details for a focused planning-module hardening slice:
1. Schema-compliance verification for task and work-package relations
2. Soft delete with counter synchronization
3. Request traceability consistency
4. Basic duplicate detection for requests and specs
5. Improved validation error messages
6. Integration test coverage for the combined slice

# Scope

**In scope:**
- Verify and preserve the real schema contract for task/spec/work-package relation fields
- Implement tm_delete() with soft delete capability
- Automatic counter synchronization after hard deletes
- Preserve request traceability through `request_refs` and the planning trace/index surfaces when creating specs/plans/tasks
- Basic duplicate detection for request/spec creation
- More actionable validation error messages for common schema mistakes
- Integration tests covering the full hardening slice

**Out of scope:**
- Undo/rollback
- Audit trail
- Performance optimizations
- Bulk operations
- Advanced duplicate-detection caching or cross-project deduplication

# Requirements

## 1. Schema Compliance Verification

The original request notes assumed a `meta.task_refs` target shape. The live planning schemas do not support that model:

- tasks do not have top-level `task_refs`
- specifications legitimately have top-level `task_refs`
- work packages legitimately have top-level `task_refs`

**Implementation:**
- Verify the live schemas and current managers align
- Remove stale planning instructions that would move valid relation fields into `meta`
- Keep implementation work focused on the real runtime hardening issues

## 2. Soft Delete

**API:**
```python
def tm_delete(
    id_: str,
    hard: bool = False,
    reason: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Soft delete a planning item.
    
    Args:
        id_: Item ID
        hard: If True, permanently delete file (default: False)
        reason: Optional deletion reason
        root: Optional project root
    
    Returns:
        Dict with id, deleted_at, hard_delete flag, and counter_sync status
    """
```

**Behavior:**
- Soft delete (default): Add `deleted: true` and `deleted_at: <timestamp>` to frontmatter, keep file
- Hard delete: Remove file from filesystem
- Call `sync_counter()` after hard delete to ensure next ID is correct
- Log deletion event

## 3. Counter Sync

**Implementation:**
- After **hard delete only**, call `sync_counter(root, kind)` automatically
- Soft delete does NOT require counter sync (file remains, ID still exists)
- `sync_counter` scans all items of kind and sets counter to highest existing ID
- Does NOT decrement to prevent gaps (gaps are acceptable)
- Ensures next ID generation is correct after file removal

## 4. Request Traceability

**Current behavior before this slice:**
- Plans and tasks did not consistently carry request traceability through the planning graph
- Reverse request traceability was being treated as a request-frontmatter mutation problem rather than a graph/index problem

**Required behavior:**
- Specs, plans, and tasks must persist `request_refs` consistently
- Reverse traceability must be discoverable from the planning graph/indexes without mutating request documents
- Validation: referenced requests must exist

**Implementation:**
- Validate referenced requests during creation
- Persist `request_refs` consistently on specs, plans, and tasks
- Use the planning trace/index outputs for reverse lookup

## 5. Duplicate Detection

**Current behavior:**
- Re-creating the same request or spec produces a new ID with no warning

**Required behavior:**
- Request and spec creation should fail clearly when an obvious duplicate already exists
- The error should identify the conflicting existing item
- A narrow override path may exist later, but it is not required for the first pass unless implementation remains simple

**Implementation:**
- Add duplicate checks at request/spec creation seams
- Prefer a simple, explainable first-pass strategy over a heavy fuzzy-matching system
- Keep the behavior consistent between helper/MCP and direct API calls

## 6. Validation Feedback

**Current behavior:**
- Raw jsonschema errors can be technically correct but unhelpful for common planning mistakes

**Required behavior:**
- Common schema mistakes should produce clearer messages with field context and expected shape
- Reference-list mistakes should point users toward the required `{ref, seq}` object structure where relevant

**Implementation:**
- Improve formatting in the existing validator layer
- Add schema descriptions/examples where that materially improves output
- Avoid introducing a second validator module unless there is a concrete need

## 7. Integration Coverage

**Required behavior:**
- Add integration coverage proving the schema fix, delete flow, counter handling, auto-reference updates, duplicate detection, and validation messaging work together
- Use isolated temporary planning roots for tests

# Constraints

1. IDs must remain stable and monotonic (no decrementing on delete)
2. Soft deleted items must remain queryable (for audit/recovery)
3. Auto-reference updates must be atomic with item creation
4. Relation-schema verification must not break existing validation

# Acceptance Criteria

1. Relation fields remain aligned with the live schemas and no invalid meta.task_refs migration is introduced
2. tm_delete() soft deletes by default, hard deletes when hard=True
3. Counter is automatically synced after hard delete and not reused to fill gaps
4. Creating spec/plan/task with request_refs preserves reverse traceability through the planning graph/indexes
5. Duplicate request/spec creation fails clearly
6. Validation output is more actionable for common planning mistakes
7. Integration coverage exists for the combined hardening slice
8. Validation passes for all planning items

# Migration

- `tm_sync_counters()`: Ensure all counters match the highest observed IDs without moving backwards
- No relation-field migration is required for this slice
