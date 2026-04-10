---
id: spec-0044
label: Multi-item batch updates and bulk operations for planning MCP
state: ready
summary: Design and implement multi-item batch operations, bulk state transitions,
  and optional result summarization to reduce token overhead for agent bulk operations
request_refs:
- request-0027
task_refs:
- ref: task-0228
  seq: 1000
- ref: task-0229
  seq: 1001
- ref: task-0230
  seq: 1002
- ref: task-0231
  seq: 1003
- ref: task-0232
  seq: 1004
standard_refs:
- standard-0006
- standard-0005
---







# Purpose

Reduce token overhead and round-trip calls for agent bulk operations by extending planning MCP to support:
1. Multi-item batch updates (different operations on multiple items in one call)
2. Bulk state transitions (multiple items to same state)
3. Optional result summarization (return counts instead of full payloads)
4. Future: compound operations (create + link, etc.)

# Scope

This specification covers:
- Backward-compatible extension of `tm_batch_update` to accept multi-item operations
- New `tm_bulk_state` operation for state transitions without full-item responses
- Optional `summary_only` flag on batch operations to minimize response payload
- Design for future compound operations (deferred implementation)
- MCP exposure of all new operations

Does NOT require:
- Query-based bulk operations (defer to future request)
- Transactional guarantees (fail-fast vs best-effort is configurable)
- Rollback semantics
- Per-item validation before batch execution

# Requirements

## 1. Multi-Item Batch Update (Extended tm_batch_update)

Current behavior (single item, multiple operations):
```python
def tm_batch_update(id: str, operations: list[dict]) -> dict
```

Extended to support:
```python
def tm_batch_update(
    items: list[dict] | None = None,  # Multi-item: [{id, operations}, ...]
    id: str | None = None,             # Legacy: single item
    operations: list[dict] | None = None,  # Legacy: operations for single item
    summary_only: bool = False,        # Return counts instead of full results
) -> dict
```

**Behavior:**
- If `items` is provided: process multi-item batch
- If `id` and `operations` provided: process single-item (backward compatible)
- If both provided: error
- If neither: error

**Response with summary_only=False (current behavior):**
```json
{
  "batch": true,
  "items_count": 3,
  "results": [
    {"id": "task-0221", "operations_executed": 2, "results": [...]},
    {"id": "task-0222", "operations_executed": 1, "results": [...]},
    {"id": "task-0223", "operations_executed": 1, "results": [...]}
  ],
  "errors": []
}
```

**Response with summary_only=True (new, minimal):**
```json
{
  "batch": true,
  "items_count": 3,
  "succeeded": 3,
  "failed": 0,
  "errors": []
}
```

## 2. Bulk State Transition (New tm_bulk_state)

```python
def tm_bulk_state(
    ids: list[str],
    new_state: str,
    summary_only: bool = True,  # Default to summary for state ops
) -> dict
```

**Behavior:**
- Transition multiple items to `new_state` in one call
- Validate state transition is legal for each item's workflow
- Return success/failure counts
- Default to summary_only=True (most agents don't need full item data)

**Response:**
```json
{
  "bulk_state": true,
  "ids_count": 6,
  "new_state": "done",
  "succeeded": 6,
  "failed": 0,
  "transitioned_ids": ["task-0221", "task-0222", ...],
  "errors": []
}
```

## 3. Result Summarization Flag

Add optional `summary_only: bool = False` parameter to:
- `tm_batch_update()`
- `tm_state()` (return just state change, no full item)
- `tm_update()` (return just confirmation, no full item)

Minimal response shape:
```json
{
  "id": "item-id",
  "operation": "state",
  "new_value": "done",
  "success": true
}
```

## 4. Compound Operations (Design Only, Deferred Implementation)

Future pattern for common workflows:
```python
def tm_create_and_link(
    kind: str, label: str, summary: str, ...,
    link_to: str, link_field: str
) -> dict
```

Enables: create spec and auto-link to request in one call instead of create + relink.

Future pattern for state + other changes:
```python
def tm_batch_compound(
    items: list[{id, state, label, summary, ...}]
) -> dict
```

These are design-forward but deferred; implement multi-item batch first.

# Constraints

1. Backward compatibility: Existing single-item `tm_batch_update(id, operations)` must work unchanged
2. Per-item validation: Each item's transition/operation must be validated
3. Fail-fast vs best-effort: Implementation may choose either strategy, document clearly
4. Maximum batch size: Set reasonable limit (e.g., 50 items) to prevent abuse
5. Response payload: summary_only=True should produce responses < 500 bytes for typical batches

# Acceptance Criteria

- [x] Design complete
- [ ] `tm_batch_update` extended to accept multi-item `items` parameter
- [ ] `tm_batch_update` backward-compatible with single-item signature
- [ ] `tm_batch_update` supports `summary_only` flag
- [ ] `tm_bulk_state(ids, new_state, summary_only)` implemented in MCP
- [ ] `tm_bulk_state` returns minimal response when summary_only=True
- [ ] All 6 tasks in archive work (task-0190-0195) can be state-transitioned with one `tm_bulk_state` call
- [ ] Agent calling pattern reduced from N individual calls to 1-2 batch calls
- [ ] Tests cover multi-item batches, state transitions, summary_only flag, backward compat
- [ ] Existing single-item `tm_batch_update` tests still pass
- [ ] Design doc includes future compound operations pattern

# Token Efficiency Impact

**Before:** Marking 6 tasks done
- 6 × `tm_state(id, "done")` calls
- 6 response payloads with full item data
- ~2KB total MCP traffic per operation

**After:** `tm_bulk_state(ids=["task-0221"...], new_state="done", summary_only=True)`
- 1 call
- 1 response payload with counts
- ~200 bytes total MCP traffic

**Savings:** 10× reduction in calls, 10× reduction in response payload for bulk operations.

# Notes

Multi-item batch is the highest-priority extension. Bulk state transitions are a common pattern that deserves its own optimized tool. Result summarization applies broadly and should become the default for operations where agents don't need full item data.

Compound operations (create_and_link) are valuable but can be deferred — start with multi-item batch + bulk state + summarization.
