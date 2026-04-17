---
id: task-278
label: Fix tight coupling in session_input_tool
state: completed
summary: Implement dependency injection for session_input_tool
request_refs:
- request-19
standard_refs:
- standard-5
- standard-6
---

## Implementation

Added dependency injection support to `session_input_store.py` following the pattern from `job_control_tool`:

1. Added `JobStoreInterface` type alias for interface consistency
2. Added optional `job_store` parameter to `build_and_persist_session_input()` with default to global store
3. Updated function to use injected `job_store` for reading job records when `provider_id` not provided
4. Updated CLI caller in `main.py:310` to pass `job_store.read_job_record` explicitly
5. Added comprehensive docstring documenting dependency injection pattern
6. Maintained backward compatibility through default parameter

## Files Modified

- `src/audiagentic/runtime/state/session_input_store.py` - Added dependency injection support
- `src/audiagentic/channels/cli/main.py` - Updated to use dependency injection pattern

## Pattern

```python
# Production: Explicit dependency injection
record = build_and_persist_session_input(
    project_root,
    job_id=job_id,
    job_store=job_store.read_job_record,  # Explicit injection
)

# Test: Mock job store
mock_store = Mock()
mock_store.read_job_record.return_value = {"provider-id": "test"}
record = build_and_persist_session_input(
    project_root,
    job_id=job_id,
    job_store=mock_store.read_job_record,
)

# Backward compatible: Uses global store
record = build_and_persist_session_input(project_root, job_id=job_id)
```

## Verification

- No direct global variable access in function body
- All callers updated to use dependency injection pattern
- Backward compatibility maintained through default parameter
- Consistent with `job_control_tool` pattern
