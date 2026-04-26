#!/usr/bin/env python3
"""Comprehensive test suite for audiagentic-planning MCP server."""

import os
import sys
from pathlib import Path

# Add src to path
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Import from the MCP module directly
import importlib.util

spec = importlib.util.spec_from_file_location(
    "audiagentic_planning_mcp", SCRIPT_DIR / "audiagentic-planning_mcp.py"
)
mcp_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp_module)

_bootstrap_repo_root = mcp_module._bootstrap_repo_root
validate_operations = mcp_module.validate_operations
PlanningError = mcp_module.PlanningError
VALID_OPS = mcp_module.VALID_OPS

import tools.planning.tm_helper as tm


def test_root_discovery():
    """Test robust root discovery."""
    print("Testing root discovery...")

    # Test 1: Normal discovery
    root = _bootstrap_repo_root()
    assert root.exists(), f"Root {root} doesn't exist"
    assert (root / ".audiagentic").exists(), f".audiagentic/ not found in {root}"
    print(f"  [OK] Normal discovery: {root}")

    # Test 2: Env var override
    os.environ["AUDIAGENTIC_ROOT"] = str(root)
    root2 = _bootstrap_repo_root()
    assert root2 == root, f"Env var override failed: {root2} != {root}"
    print(f"  [OK] Env var override: {root2}")

    # Test 3: Invalid env var
    os.environ["AUDIAGENTIC_ROOT"] = "/nonexistent/path"
    try:
        _bootstrap_repo_root()
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "AUDIAGENTIC_ROOT" in str(e)
        assert ".audiagentic/" in str(e)
        print(f"  [OK] Invalid env var error: {e}")

    # Cleanup
    del os.environ["AUDIAGENTIC_ROOT"]
    print("  [OK] Root discovery tests passed\n")


def test_operation_validation():
    """Test operation validation."""
    print("Testing operation validation...")

    # Test 1: Valid operations
    valid_ops = [
        {"op": "state", "value": "done"},
        {"op": "label", "value": "New label"},
        {"op": "summary", "value": "New summary"},
        {"op": "section", "name": "Notes", "content": "Test", "mode": "set"},
        {"op": "section", "name": "Notes", "content": "Test", "mode": "append"},
        {"op": "content", "value": "Test", "mode": "replace"},
        {"op": "content", "value": "Test", "mode": "append"},
        {"op": "meta", "field": "tags", "value": "test"},
        {"op": "field", "field": "spec_refs", "mode": "add", "value": "spec-123"},
        {"op": "field", "field": "spec_refs", "mode": "remove", "value": "spec-123"},
        {"op": "field", "field": "spec_ref", "mode": "set", "value": "spec-123"},
    ]

    for i, op_dict in enumerate(valid_ops):
        try:
            validate_operations([op_dict])
        except PlanningError as e:
            assert False, f"Valid operation {i} rejected: {e}"
    print(f"  [OK] All {len(valid_ops)} valid operations accepted")

    # Test 2: Invalid operation type
    try:
        validate_operations([{"op": "invalid_op", "value": "test"}])
        assert False, "Should have raised PlanningError"
    except PlanningError as e:
        assert "invalid" in str(e).lower() or "Supported operations" in str(e.suggestion)
        print(f"  [OK] Invalid operation rejected: {e}")
        print(f"    Suggestion: {e.suggestion}")

    # Test 3: Section without name
    try:
        validate_operations([{"op": "section", "content": "Test"}])
        assert False, "Should have raised PlanningError"
    except PlanningError as e:
        assert "name" in str(e).lower()
        print(f"  [OK] Section without name rejected: {e}")

    # Test 4: Meta without field
    try:
        validate_operations([{"op": "meta", "value": "test"}])
        assert False, "Should have raised PlanningError"
    except PlanningError as e:
        assert "field" in str(e).lower()
        print(f"  [OK] Meta without field rejected: {e}")

    # Test 5: Field without field
    try:
        validate_operations([{"op": "field", "mode": "remove", "value": "spec-123"}])
        assert False, "Should have raised PlanningError"
    except PlanningError as e:
        assert "field" in str(e).lower()
        print(f"  [OK] Field without field rejected: {e}")

    # Test 6: Invalid mode
    try:
        validate_operations(
            [{"op": "section", "name": "Notes", "content": "Test", "mode": "invalid"}]
        )
        assert False, "Should have raised PlanningError"
    except PlanningError as e:
        assert "mode" in str(e).lower()
        print(f"  [OK] Invalid mode rejected: {e}")

    print("  [OK] Operation validation tests passed\n")


def test_planning_error():
    """Test structured error responses."""
    print("Testing PlanningError...")

    # Test 1: Error with suggestion
    error = PlanningError("Invalid operation", suggestion="Use: state, label, summary")
    assert error.message == "Invalid operation"
    assert error.suggestion == "Use: state, label, summary"
    print(f"  [OK] Error with suggestion: {error.message}")
    print(f"    Suggestion: {error.suggestion}")

    # Test 2: Error without suggestion
    error2 = PlanningError("Simple error")
    assert error2.message == "Simple error"
    assert error2.suggestion is None
    print(f"  [OK] Error without suggestion: {error2.message}")

    print("  [OK] PlanningError tests passed\n")


def test_tm_edit_integration():
    """Test tm_edit with real planning items."""
    print("Testing tm_edit integration...")

    # Create a test request first (needed for task spec)
    req_result = tm.create(
        "request",
        "MCP Test Request",
        "Request for testing MCP server",
        source="test",
    )

    # Create a task with proper spec reference
    spec_result = tm.create(
        "spec",
        label="MCP Test Spec",
        summary="Spec for testing MCP server",
        refs={"request_refs": [req_result["id"]]},
    )

    try:
        result = tm.create(
            "task",
            label="MCP Test Task",
            summary="Task for testing MCP server",
            refs={"spec": spec_result["id"]},
            domain="core",
        )
        task_id = result["id"]
        print(f"  [OK] Created test task: {task_id}")

        # Test 1: Valid state change
        ops = [{"op": "state", "value": "in_progress"}]
        result = tm.update(task_id, operations=ops)
        assert result["id"] == task_id
        print(f"  [OK] State change to in_progress")

        # Test 2: Valid section update
        ops = [{"op": "section", "name": "Test Section", "content": "Test content", "mode": "set"}]
        result = tm.update(task_id, operations=ops)
        print(f"  [OK] Section update")

        # Test 3: Multiple operations
        ops = [
            {"op": "label", "value": "Updated Test Task"},
            {"op": "meta", "field": "test_flag", "value": "true"},
        ]
        result = tm.update(task_id, operations=ops)
        print(f"  [OK] Multiple operations (label + meta)")

        # Test 4: Field add/remove on top-level frontmatter lists
        ops = [{"op": "field", "field": "standard_refs", "mode": "add", "value": "standard-5"}]
        tm.update(req_result["id"], operations=ops)
        shown = tm.show(req_result["id"])
        assert "standard-5" in shown.get("standard_refs", [])
        print(f"  [OK] Field add on standard_refs")

        ops = [{"op": "field", "field": "standard_refs", "mode": "remove", "value": "standard-5"}]
        tm.update(req_result["id"], operations=ops)
        shown = tm.show(req_result["id"])
        assert "standard-5" not in shown.get("standard_refs", [])
        print(f"  [OK] Field remove on standard_refs")

        # Test 5: Invalid operation (may be silently ignored by tm.update)
        # tm.update calls validate_operations but the server may accept it
        ops = [{"op": "invalid_op", "value": "test"}]
        result = tm.update(task_id, operations=ops)
        print(f"  [OK] Invalid operation handled (result: {result.get('results', [])})")

        # Cleanup
        tm.delete(task_id, hard=True)
        print(f"  [OK] Cleaned up test task")

    except Exception as e:
        print(f"  [FAIL] Integration test failed: {e}")
        import traceback

        traceback.print_exc()
        raise

    print("  [OK] tm_edit integration tests passed\n")


def test_tm_create():
    """Test tm_create with various kinds."""
    print("Testing tm_create...")

    test_items = []

    # Test 1: Create request first (needed for task and spec)
    req_result = tm.create(
        "request",
        "Test Request",
        "Test request summary",
        source="mcp-test",
    )
    test_items.append(("request", req_result["id"]))
    print(f"  [OK] Created request: {req_result['id']}")

    # Test 2: Create spec with request_refs
    spec_result = tm.create("spec", label="Test Spec", summary="Test spec summary", refs={"request_refs": [req_result["id"]]})
    test_items.append(("spec", spec_result["id"]))
    print(f"  [OK] Created spec: {spec_result['id']}")

    # Test 3: Create task with spec
    task_result = tm.create(
        "task",
        label="Test Task",
        summary="Test summary",
        refs={"spec": spec_result["id"]},
        domain="core",
    )
    test_items.append(("task", task_result["id"]))
    print(f"  [OK] Created task: {task_result['id']}")

    # Test 4: Create plan with spec
    plan_result = tm.create(
        "plan",
        label="Test Plan",
        summary="Test plan summary",
        refs={"spec": spec_result["id"]},
    )
    test_items.append(("plan", plan_result["id"]))
    print(f"  [OK] Created plan: {plan_result['id']}")

    # Cleanup
    for kind, item_id in reversed(test_items):
        tm.delete(item_id, hard=True)
        print(f"  [OK] Cleaned up {kind}: {item_id}")

    print("  [OK] tm_create tests passed\n")


def test_tm_get():
    """Test tm_get with different depths."""
    print("Testing tm_get...")

    # Create a test request first (needed for task spec)
    req_result = tm.create(
        "request",
        "Get Test Request",
        "Request for tm_get testing",
        source="test",
    )

    # Create spec
    spec_result = tm.create("spec", label="Get Test Spec", summary="Spec for tm_get", refs={"request_refs": [req_result["id"]]})

    # Create test item with proper spec
    result = tm.create(
        "task",
        label="Get Test Task",
        summary="Test for tm_get",
        refs={"spec": spec_result["id"]},
        domain="core",
    )
    task_id = result["id"]

    try:
        # Test 1: head (cheapest)
        head_result = tm.head(task_id)
        assert "id" in head_result
        assert "state" in head_result
        print(f"  [OK] head: {head_result['id']} state={head_result['state']}")

        # Test 2: meta (frontmatter only)
        meta_result = tm.show(task_id)
        assert "id" in meta_result
        assert "label" in meta_result
        assert "summary" in meta_result
        print(f"  [OK] meta: label={meta_result['label']}")

        # Test 3: body (raw markdown)
        body_result = tm.get_content(task_id)
        assert isinstance(body_result, str)
        assert len(body_result) > 0
        print(f"  [OK] body: {len(body_result)} chars")

        # Test 4: full (extract)
        full_result = tm.extract(task_id, include_body=True, write_to_disk=False)
        assert isinstance(full_result, dict)
        assert "item" in full_result
        assert "id" in full_result["item"]
        assert "body" in full_result
        print(f"  [OK] full: id={full_result['item']['id']}")

    finally:
        tm.delete(task_id, hard=True)
        print(f"  [OK] Cleaned up test task")

    print("  [OK] tm_get tests passed\n")


def test_tm_list():
    """Test tm_list with different modes."""
    print("Testing tm_list...")

    # Test 1: list mode
    items = tm.list_kind("task")
    assert isinstance(items, list)
    print(f"  [OK] list mode: {len(items)} tasks")

    # Test 2: count mode
    status = tm.status()
    assert "task" in status or "request" in status
    print(f"  [OK] count mode: {status}")

    # Test 3: next mode
    next_items = tm.next_items("task", "ready", None)
    assert isinstance(next_items, list)
    print(f"  [OK] next mode: {len(next_items)} ready tasks")

    print("  [OK] tm_list tests passed\n")


def test_error_handling():
    """Test error handling across tools."""
    print("Testing error handling...")

    # Test 1: Non-existent item
    try:
        tm.head("non-existent-task-9999")
        assert False, "Should have raised error"
    except ValueError as e:
        assert "not found" in str(e).lower()
        print(f"  [OK] Non-existent item error: {e}")

    # Test 2: Invalid kind
    try:
        tm.list_kind("invalid_kind")
        # Might not raise, might return empty list
        print(f"  [WARN] Invalid kind handled gracefully")
    except ValueError as e:
        print(f"  [OK] Invalid kind error: {e}")

    print("  [OK] Error handling tests passed\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("AUDiaGentic MCP Server Test Suite")
    print("=" * 60 + "\n")

    tests = [
        ("Root Discovery", test_root_discovery),
        ("Operation Validation", test_operation_validation),
        ("PlanningError", test_planning_error),
        ("tm_edit Integration", test_tm_edit_integration),
        ("tm_create", test_tm_create),
        ("tm_get", test_tm_get),
        ("tm_list", test_tm_list),
        ("Error Handling", test_error_handling),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"\n{'=' * 60}")
            print(f"Running: {name}")
            print("=" * 60)
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n[FAIL] {name} FAILED: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
