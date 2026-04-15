---
id: spec-018
label: Planning Module Critical Fixes Specification
state: draft
summary: Specification for fixing critical bugs and architectural issues in planning
  module
request_refs:
- request-016
task_refs: []
standard_refs:
- standard-0006
- standard-0005
---


# Purpose

Fix critical bugs and address architectural issues identified in comprehensive planning module reviews (2026-04-14). The planning module is functionally robust but has correctness bugs, code duplication, and scalability concerns that need immediate attention.

# Scope

**In Scope:**
- Fix critical bugs in `api.py` (create_with_content drops standard_refs, update_content dead code)
- Fix duplicated validation logic in `val_mgr.py`
- Consolidate duplicated creation logic in `new()` and `create_with_content()`
- Add cycle detection to standards cascade
- Improve error messages in validation
- Add atomic write guarantee for file operations

**Out of Scope:**
- Complete api.py refactoring (God Object - tracked separately)
- Adding rollback for multi-step operations (tracked separately)
- Event log rotation (tracked separately)
- Claims expiry mechanism overhaul (tracked separately)

# Requirements

## R1: Fix create_with_content() standard_refs Bug

**Priority:** CRITICAL

**Issue:** `create_with_content()` accepts `standard_refs` parameter but silently drops it for spec, task, plan, and wp creation. Only `new()` correctly passes `standard_refs` to manager create methods.

**Fix:**
```python
# In create_with_content() spec branch:
path = self.spec_mgr.create(
    id_, label, summary, 
    request_refs=request_refs or [],
    standard_refs=standard_refs  # ADD THIS
)

# Same fix for task, plan, wp branches
```

**Verification:**
- Create spec via `create_with_content()` with `standard_refs=['standard-0006']`
- Verify spec frontmatter contains `standard_refs: [standard-0006]`
- Same test for task, plan, wp

## R2: Remove Dead Code in update_content() Section Mode

**Priority:** CRITICAL

**Issue:** `update_content()` mode="section" has two identical regex match-and-replace blocks (lines 498-513 and 514-525). The second block overwrites the first, making the first block dead code. Additionally, inconsistent blank-line handling.

**Fix:**
- Remove first block (lines 498-513)
- Keep only one match-and-replace pass
- Ensure consistent formatting (blank line after section header)

**Verification:**
- Update section content via `update_content(id, content, mode='section', section='Summary')`
- Verify section updated correctly with consistent formatting
- No duplicate processing in logs

## R3: Consolidate new() and create_with_content() Logic

**Priority:** HIGH

**Issue:** Both methods have ~120 lines of nearly identical logic (kind normalization, duplicate check, validation, manager dispatch, hooks, indexing). Any bug fix must be applied in two places.

**Fix:**
```python
def _create_item(self, kind, id_, label, summary, **kwargs) -> Path:
    """Shared creation logic for new() and create_with_content()."""
    # All validation and manager dispatch here
    return path

def new(self, kind, label, summary, **kwargs):
    path = self._create_item(kind, id_, label, summary, **kwargs)
    self.hooks.run("after_create", ...)
    self.index()
    return self._find(id_)

def create_with_content(self, kind, label, summary, content, **kwargs):
    path = self._create_item(kind, id_, label, summary, **kwargs)
    self.update_content(id_, content)
    self.hooks.run("after_create", ...)
    self.index()
    return self._find(id_)
```

**Verification:**
- Create items via both methods
- Verify identical behavior
- Single code path for validation/dispatch

## R4: Fix val_mgr.py Duplicated Validation

**Priority:** HIGH

**Issue:** `validate_all()` runs section validation twice (lines 78-95 and 97-105) and iterates items 6+ times via separate `scan_items()` calls.

**Fix:**
```python
def validate_all(self) -> list[str]:
    errors = []
    errors.extend(self.config.validate())
    
    # Single scan
    items = list(scan_items(self.root))
    
    # Build indexes once
    specs_by_request = {}
    tasks_by_spec = {}
    for item in items:
        # Build indexes...
    
    # Single validation pass
    ids = set()
    for item in items:
        # Duplicate ID check
        # JSON schema validation
        # Required sections (merge REQ_SECTIONS + guidance)
        # Filename rules
        # Directory structure
    
    # Referential integrity pass
    for item in items:
        # Request/spec/task linkage checks
    
    return errors
```

**Verification:**
- Run validation on project with 100+ planning items
- Verify single pass through items (profile if needed)
- No duplicate error messages

## R5: Add Cycle Detection to Standards Cascade

**Priority:** MEDIUM

**Issue:** `effective_standard_refs()` in `standards.py` and `ext_mgr.py` can infinite-loop on circular task hierarchies (task A parent = task B, task B parent = task A).

**Fix:**
```python
def effective_standard_refs(item, items_by_id, _visited=None):
    _visited = _visited or set()
    if item.data["id"] in _visited:
        return []  # Break cycle
    _visited.add(item.data["id"])
    
    refs = list(item.data.get('standard_refs', []) or [])
    
    if item.kind == 'task':
        spec = items_by_id.get(item.data.get('spec_ref'))
        if spec:
            refs.extend(spec.data.get('standard_refs', []) or [])
        parent = items_by_id.get(item.data.get('parent_task_ref'))
        if parent:
            # Pass _visited to prevent cycles
            refs.extend(effective_standard_refs(parent, items_by_id, _visited))
    # ... similar for wp
    
    # Deduplicate
    out = []
    for r in refs:
        if r not in out:
            out.append(r)
    return out
```

**Verification:**
- Create circular task hierarchy (A → B → A)
- Call `effective_standard_refs()` on task A
- Verify no infinite loop, returns standards without crash

## R6: Improve Validation Error Messages

**Priority:** MEDIUM

**Issue:** `_format_error()` in `val_mgr.py` produces confusing messages for nested schema validation failures.

**Fix:**
```python
def _format_error(self, error: ValidationError) -> str:
    # For nested errors, use built-in message
    if len(error.path) > 1:
        return error.message
    
    # Only simplify top-level errors
    if error.validator == "required" and len(error.path) <= 1:
        missing = ", ".join(repr(m) for m in error.validator_value)
        return f"missing required field(s): {missing}"
    
    return error.message
```

**Verification:**
- Create item with nested validation error (e.g., invalid task_refs[0])
- Verify error message clearly indicates location and issue

## R7: Add Atomic Write Guarantee

**Priority:** MEDIUM

**Issue:** `dump_markdown()` in `fs/write.py` writes directly to file. Crash mid-write leaves corrupt file.

**Fix:**
```python
def dump_markdown(path: Path, data: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    content = f"---\n{fm}\n---\n\n{body.rstrip()}\n"
    
    # Atomic write: write to temp, then rename
    temp_path = path.with_suffix('.tmp')
    temp_path.write_text(content, encoding='utf-8')
    temp_path.replace(path)  # Atomic on POSIX and NTFS
```

**Verification:**
- Simulate crash during write (kill process)
- Verify no corrupt files left behind
- File is either old version or new version, never partial

# Constraints

- Maintain backward compatibility with existing planning items
- No breaking changes to API signatures
- Keep JSON schema validation unchanged
- Maintain existing test coverage

# Acceptance Criteria

## AC1: create_with_content() Bug Fixed
- [ ] Spec created via `create_with_content()` with `standard_refs` contains those refs
- [ ] Task created via `create_with_content()` with `standard_refs` contains those refs
- [ ] Plan created via `create_with_content()` with `standard_refs` contains those refs
- [ ] WP created via `create_with_content()` with `standard_refs` contains those refs
- [ ] Test added to prevent regression

## AC2: Dead Code Removed
- [ ] `update_content()` section mode has single regex block
- [ ] Section updates produce consistent formatting
- [ ] No performance regression (single pass)

## AC3: Creation Logic Consolidated
- [ ] `_create_item()` shared method exists
- [ ] Both `new()` and `create_with_content()` use it
- [ ] Identical behavior verified via tests
- [ ] Code duplication reduced by >50%

## AC4: Validation Optimized
- [ ] Single `scan_items()` call in `validate_all()`
- [ ] Single validation pass per item
- [ ] No duplicate error messages
- [ ] Performance improved for 100+ item projects

## AC5: Cycle Detection Added
- [ ] `effective_standard_refs()` accepts `_visited` parameter
- [ ] Circular task hierarchy doesn't cause infinite loop
- [ ] Standards correctly deduplicated

## AC6: Error Messages Improved
- [ ] Nested validation errors use clear messages
- [ ] Top-level errors remain simplified
- [ ] No regression in existing error clarity

## AC7: Atomic Writes
- [ ] `dump_markdown()` uses temp file + rename
- [ ] No corrupt files after simulated crash
- [ ] Cross-platform compatibility verified (Windows, Linux)

## AC8: Tests Pass
- [ ] All existing tests pass
- [ ] New tests added for each fix
- [ ] No test coverage regression

# Implementation Notes

**Order of Implementation:**
1. R1: Fix create_with_content() standard_refs (quick win, high impact)
2. R2: Remove dead code in update_content() (quick win)
3. R7: Add atomic writes (safety improvement)
4. R4: Fix val_mgr.py duplication (performance improvement)
5. R5: Add cycle detection (safety improvement)
6. R6: Improve error messages (UX improvement)
7. R3: Consolidate creation logic (largest refactor, do last)

**Risk Mitigation:**
- Add tests before refactoring (R3)
- Verify existing tests pass after each change
- Profile validation performance before/after (R4)
- Test atomic writes on both Windows and Linux (R7)

# References

- [Planning System Documentation](../docs/knowledge/pages/systems/system-planning.md)
- [Using the Planning System](../docs/knowledge/pages/guides/guide-using-planning.md)
- Review 1: Critical Review: Planning Module (2026-04-14)
- Review 2: Planning Module Code Review (2026-04-14)
- Review 3: Architectural Review (2026-04-14)
