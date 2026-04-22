---
id: task-336
label: Integrate relationship validation into managers
state: done
summary: '"Add RelationshipConfig validation to manager create() methods"'
spec_ref: spec-33
request_refs: []
standard_refs:
- standard-5
- standard-6
---










## Description

Enable required-ref enforcement in `PlanningAPI._create_item()`. The validation call exists at [api.py:1000](src/audiagentic/planning/app/api.py#L1000) but uses `validate_required=False`, so required refs (e.g. `request_refs` on spec, `spec_refs` on plan) are never enforced.

## Current State

`api.py:1000–1004` calls `self.relationship_config.validate_refs(kind, frontmatter, validate_required=False)`.

The individual manager classes (`spec_mgr.py`, `task_mgr.py` etc.) referenced in the original task description **no longer exist** — all create logic was consolidated into `PlanningAPI._create_item()`. The original task description was stale.

Relationship rules are in `.audiagentic/planning/config/profiles.yaml` under `planning.relationship_config`. Current `required_for_children`:
- `spec`: `[request_refs]`
- `plan`: `[spec_refs]`
- `request`, `task`, `wp`, `standard`: `[]`

## Required Changes

### 1. Enable validation in api.py

Change [api.py:1001](src/audiagentic/planning/app/api.py#L1001):
```python
# Before
relationship_errors = self.relationship_config.validate_refs(
    kind, frontmatter, validate_required=False
)
# After
relationship_errors = self.relationship_config.validate_refs(
    kind, frontmatter, validate_required=True
)
```

### 2. Audit profiles.yaml required_for_children

Verify each kind's `required_for_children` is correct and complete. Gaps to check:
- `wp`: should `plan_ref` be required? Currently `[]`
- `task`: should `spec_ref` be required? Currently `[]`
- `standard`: nothing expected

Update profiles.yaml if any required refs are missing.

### 3. Check all create paths

Verify that `create_with_content()` ([api.py:1141](src/audiagentic/planning/app/api.py#L1141)) and `_create_generic_item()` ([api.py:1019](src/audiagentic/planning/app/api.py#L1019)) also pass through relationship validation. If they bypass `_create_item()`, they need the validation call too.

### 4. Verify existing creation flows still work

After enabling, confirm:
- Creating a spec with valid `request_refs` succeeds
- Creating a spec with no `request_refs` is rejected with clear error
- Creating a task without `spec_ref` succeeds (not required per config)

## Acceptance Criteria

1. `validate_required=True` set in `_create_item()` at api.py:1001
2. profiles.yaml `required_for_children` verified and correct for all kinds
3. All create paths validate refs or call validation directly
4. Missing required refs raise `ValueError` with clear message before file is written
5. Existing tests pass; add regression test for required-ref rejection on spec without request_refs

# Notes

## 2026-04-22 Implementation

- Fixed `profiles.yaml`: wp `required_for_children` changed from `[plan_ref, task_refs]` to `[plan_ref]` — task_refs added post-creation so cannot be required at create time
- Changed `api.py:1001` `validate_required=False` → `validate_required=True`
- Spec and plan required-ref enforcement now backed by RelationshipConfig in addition to existing `_require_request_refs_for_spec`
