---
id: support-0002
label: MCP Layer Root Directory Configurability Proposal
state: active
role: execution_reference
supports:
- task-0189
owner: planning-team
status: active
summary: Proposal for adding root parameter to MCP helper functions
---

# MCP Layer Root Directory Configurability Proposal

## Problem

The MCP helper layer (`tools/planning/tm_helper.py`) currently uses a hardcoded `_ROOT` variable that is auto-detected at module import time. This makes it impossible to:

1. Run planning operations in isolated test directories
2. Support multiple project roots simultaneously
3. Create planning items without affecting the main project

## Current Implementation

```python
# tools/planning/tm_helper.py

def _find_project_root() -> Path:
    """Auto-detect project root."""
    # Search strategy...
    return root

_ROOT = _find_project_root()  # Set once at import
_api = PlanningAPI(_ROOT)     # Fixed to auto-detected root
```

## Proposed Solution

### Option 1: Explicit Root Parameter (Recommended)

Add optional `root` parameter to all helper functions:

```python
# tools/planning/tm_helper.py

def new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
    workflow: str | None = None,
    root: Path | None = None,  # NEW
) -> dict[str, Any]:
    """Create a new task.
    
    Args:
        root: Optional project root. If None, uses auto-detected root.
    """
    project_root = root or _ROOT
    api = PlanningAPI(project_root)
    
    item = api.new(
        "task",
        label=label,
        summary=summary,
        spec=spec,
        domain=domain,
        target=target,
        parent=parent,
        workflow=workflow,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}
```

**Usage:**
```python
# Use default (auto-detected) root
task = tm.new_task("Label", "Summary", "spec-0001")

# Use isolated test directory
from pathlib import Path
test_root = Path("/tmp/test-project")
task = tm.new_task("Label", "Summary", "spec-0001", root=test_root)
```

### Option 2: Context Manager

For test scenarios, use a context manager:

```python
# tools/planning/tm_helper.py

from contextlib import contextmanager

@contextmanager
def with_root(root: Path):
    """Context manager for temporary root directory."""
    original_root = _ROOT
    original_api = _api
    try:
        _ROOT = root
        _api = PlanningAPI(root)
        yield
    finally:
        _ROOT = original_root
        _api = original_api

# Usage in tests
with tm.with_root(test_root):
    task = tm.new_task("Label", "Summary", "spec-0001")
```

### Option 3: Module-Level Configuration

Add module-level configuration:

```python
# tools/planning/tm_helper.py

_current_root: Path | None = None

def set_root(root: Path) -> None:
    """Set the project root for all subsequent operations."""
    global _current_root, _api
    _current_root = root
    _api = PlanningAPI(root)

def get_root() -> Path:
    """Get the current project root."""
    return _current_root or _ROOT

# Usage
tm.set_root(test_root)
task = tm.new_task("Label", "Summary", "spec-0001")
```

## Recommendation

**Use Option 1 (Explicit Root Parameter)** because:

1. **Clear intent** - Root is explicit in function signature
2. **Thread-safe** - No global state mutation
3. **Testable** - Easy to mock in tests
4. **Backward compatible** - Existing code works without changes
5. **Flexible** - Supports both default and custom roots

## Implementation Plan

1. Add `root: Path | None = None` parameter to all helper functions
2. Update all functions to use `project_root = root or _ROOT`
3. Add tests in `test_id_counter_and_isolation.py`
4. Update documentation

## Benefits

- ✅ Isolated test directories
- ✅ No pollution of main project
- ✅ Concurrent planning operations on different roots
- ✅ Better test coverage
- ✅ Regression prevention for ID counter issues
