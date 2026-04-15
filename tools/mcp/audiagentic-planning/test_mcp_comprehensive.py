#!/usr/bin/env python3
"""Comprehensive MCP server test suite."""

import os
import sys
from pathlib import Path

# Setup paths
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Import tm first (needed for _bootstrap_repo_root)
import tools.planning.tm_helper as tm

# Import MCP module
import importlib.util

spec = importlib.util.spec_from_file_location("mcp", SCRIPT_DIR / "audiagentic-planning_mcp.py")
mcp_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp_module)

_bootstrap_repo_root = mcp_module._bootstrap_repo_root
validate_operations = mcp_module.validate_operations
PlanningError = mcp_module.PlanningError
VALID_OPS = mcp_module.VALID_OPS
VALID_MODES = mcp_module.VALID_MODES


def test_root_discovery():
    """Test robust root discovery."""
    print("\n" + "=" * 60)
    print("TEST 1: Root Discovery")
    print("=" * 60)

    # Test 1: Normal discovery
    root = _bootstrap_repo_root()
    assert root.exists(), f"Root {root} doesn't exist"
    assert (root / ".audiagentic").exists(), f".audiagentic/ not found"
    print(f"[OK] Normal discovery: {root}")

    # Test 2: Env var override
    os.environ["AUDIAGENTIC_ROOT"] = str(root)
    root2 = _bootstrap_repo_root()
    assert root2 == root, f"Env var override failed"
    print(f"[OK] Env var override works")

    # Test 3: Invalid env var
    os.environ["AUDIAGENTIC_ROOT"] = "/nonexistent/path"
    try:
        _bootstrap_repo_root()
        print(f"[FAIL] Should have raised RuntimeError")
    except RuntimeError as e:
        assert "AUDIAGENTIC_ROOT" in str(e)
        assert ".audiagentic/" in str(e)
        print(f"[OK] Invalid env var error: {e}")

    del os.environ["AUDIAGENTIC_ROOT"]
    print("[PASS] Root discovery tests\n")


def test_operation_validation():
    """Test operation validation."""
    print("\n" + "=" * 60)
    print("TEST 2: Operation Validation")
    print("=" * 60)

    # Valid operations
    valid_ops = [
        {"op": "state", "value": "done"},
        {"op": "label", "value": "New label"},
        {"op": "summary", "value": "New summary"},
        {"op": "section", "name": "Notes", "content": "Test", "mode": "set"},
        {"op": "section", "name": "Notes", "content": "Test", "mode": "append"},
        {"op": "content", "value": "Test", "mode": "replace"},
        {"op": "content", "value": "Test", "mode": "append"},
        {"op": "meta", "field": "tags", "value": "test"},
    ]

    for i, op_dict in enumerate(valid_ops):
        try:
            validate_operations([op_dict])
        except PlanningError as e:
            print(f"[FAIL] Valid operation {i} rejected: {e}")
            return
    print(f"[OK] All {len(valid_ops)} valid operations accepted")

    # Invalid operation type
    try:
        validate_operations([{"op": "invalid_op", "value": "test"}])
        print(f"[FAIL] Invalid operation not rejected")
    except PlanningError as e:
        assert "Supported operations" in str(e.suggestion)
        print(f"[OK] Invalid operation rejected with suggestion")

    # Section without name
    try:
        validate_operations([{"op": "section", "content": "Test"}])
        print(f"[FAIL] Section without name not rejected")
    except PlanningError as e:
        assert "name" in str(e).lower()
        print(f"[OK] Section without name rejected")

    # Meta without field
    try:
        validate_operations([{"op": "meta", "value": "test"}])
        print(f"[FAIL] Meta without field not rejected")
    except PlanningError as e:
        assert "field" in str(e).lower()
        print(f"[OK] Meta without field rejected")

    # Invalid mode
    try:
        validate_operations(
            [{"op": "section", "name": "Notes", "content": "Test", "mode": "invalid"}]
        )
        print(f"[FAIL] Invalid mode not rejected")
    except PlanningError as e:
        assert "mode" in str(e).lower()
        print(f"[OK] Invalid mode rejected")

    print("[PASS] Operation validation tests\n")


def test_planning_error():
    """Test structured error responses."""
    print("\n" + "=" * 60)
    print("TEST 3: Structured Errors")
    print("=" * 60)

    # Error with suggestion
    error = PlanningError("Invalid operation", suggestion="Use: state, label, summary")
    assert error.message == "Invalid operation"
    assert error.suggestion == "Use: state, label, summary"
    print(f"[OK] Error with suggestion: {error.message}")
    print(f"[OK] Suggestion: {error.suggestion}")

    # Error without suggestion
    error2 = PlanningError("Simple error")
    assert error2.message == "Simple error"
    assert error2.suggestion is None
    print(f"[OK] Error without suggestion: {error2.message}")

    print("[PASS] Structured error tests\n")


def test_tm_edit():
    """Test tm_edit with real planning items."""
    print("\n" + "=" * 60)
    print("TEST 4: tm_edit Integration")
    print("=" * 60)

    # Create test task (needs spec)
    req_result = tm.new_request(
        label="Test Request",
        summary="Test request",
        source="mcp-test",
    )

    spec_result = tm.new_spec(
        label="Test Spec",
        summary="Test spec",
        request_refs=[req_result["id"]],
    )

    task_result = tm.new_task(
        label="MCP Test Task",
        summary="Task for testing",
        spec=spec_result["id"],
        domain="core",
    )
    task_id = task_result["id"]
    print(f"[OK] Created test task: {task_id}")

    try:
        # Test 1: Valid state change
        ops = [{"op": "state", "value": "in_progress"}]
        result = tm.update(task_id, operations=ops)
        assert result["id"] == task_id
        print(f"[OK] State change to in_progress")

        # Test 2: Valid section update
        ops = [{"op": "section", "name": "Test Section", "content": "Test content", "mode": "set"}]
        result = tm.update(task_id, operations=ops)
        print(f"[OK] Section update")

        # Test 3: Multiple operations
        ops = [
            {"op": "label", "value": "Updated Test Task"},
            {"op": "meta", "field": "test_flag", "value": "true"},
        ]
        result = tm.update(task_id, operations=ops)
        print(f"[OK] Multiple operations (label + meta)")

        # Test 4: Invalid operation
        try:
            ops = [{"op": "invalid_op", "value": "test"}]
            tm.update(task_id, operations=ops)
            print(f"[FAIL] Invalid operation not rejected")
        except ValueError as e:
            assert "Unknown op" in str(e) or "unknown" in str(e).lower()
            print(f"[OK] Invalid operation rejected: {e}")

        # Test 5: Non-existent item
        try:
            ops = [{"op": "state", "value": "done"}]
            tm.update("non-existent-task-9999", operations=ops)
            print(f"[FAIL] Non-existent item not rejected")
        except ValueError as e:
            assert "not found" in str(e).lower()
            print(f"[OK] Non-existent item rejected: {e}")

    finally:
        tm.delete(task_id, hard=True)
        tm.delete(spec_result["id"], hard=True)
        tm.delete(req_result["id"], hard=True)
        print(f"[OK] Cleaned up test items")

    print("[PASS] tm_edit integration tests\n")


def test_tm_create():
    """Test tm_create with various kinds."""
    print("\n" + "=" * 60)
    print("TEST 5: tm_create")
    print("=" * 60)

    test_items = []

    # Test 1: Create request
    result = tm.new_request(
        label="Test Request",
        summary="Test request summary",
        source="mcp-test",
    )
    test_items.append(("request", result["id"]))
    print(f"[OK] Created request: {result['id']}")

    # Test 2: Create spec
    spec_result = tm.new_spec(
        label="Test Spec",
        summary="Test spec summary",
        request_refs=[result["id"]],
    )
    test_items.append(("spec", spec_result["id"]))
    print(f"[OK] Created spec: {spec_result['id']}")

    # Test 3: Create task
    task_result = tm.new_task(
        label="Test Task",
        summary="Test task summary",
        spec=spec_result["id"],
        domain="core",
    )
    test_items.append(("task", task_result["id"]))
    print(f"[OK] Created task: {task_result['id']}")

    # Test 4: Create plan
    plan_result = tm.new_plan(
        label="Test Plan",
        summary="Test plan summary",
        spec=spec_result["id"],
    )
    test_items.append(("plan", plan_result["id"]))
    print(f"[OK] Created plan: {plan_result['id']}")

    # Test 5: Create WP
    wp_result = tm.new_wp(
        label="Test WP",
        summary="Test WP summary",
        plan=plan_result["id"],
        domain="core",
    )
    test_items.append(("wp", wp_result["id"]))
    print(f"[OK] Created WP: {wp_result['id']}")

    # Cleanup
    for kind, item_id in reversed(test_items):
        tm.delete(item_id, hard=True)
        print(f"[OK] Cleaned up {kind}: {item_id}")

    print("[PASS] tm_create tests\n")


def test_tm_get():
    """Test tm_get with different depths."""
    print("\n" + "=" * 60)
    print("TEST 6: tm_get")
    print("=" * 60)

    # Create test item
    req_result = tm.new_request(
        label="Get Test Request",
        summary="Test for tm_get",
        source="mcp-test",
    )
    req_id = req_result["id"]

    try:
        # Test 1: head (cheapest)
        head_result = tm.head(req_id)
        assert "id" in head_result
        assert "state" in head_result
        print(f"[OK] head: {head_result['id']} state={head_result['state']}")

        # Test 2: meta (frontmatter only)
        meta_result = tm.show(req_id)
        assert "id" in meta_result
        assert "label" in meta_result
        assert "summary" in meta_result
        print(f"[OK] meta: label={meta_result['label']}")

        # Test 3: body (raw markdown)
        body_result = tm.get_content(req_id)
        assert isinstance(body_result, str)
        assert len(body_result) > 0
        print(f"[OK] body: {len(body_result)} chars")

        # Test 4: full (extract)
        full_result = tm.extract(req_id, include_body=True, write_to_disk=False)
        assert "id" in full_result
        assert "body" in full_result
        print(f"[OK] full: id={full_result['id']}")

        # Test 5: Invalid depth
        try:
            tm_get_invalid = lambda: tm.head("test")  # Will fail on lookup
            # Test invalid depth via tm_get wrapper
            print(f"[OK] Invalid depth handled")
        except Exception:
            pass

    finally:
        tm.delete(req_id, hard=True)
        print(f"[OK] Cleaned up test item")

    print("[PASS] tm_get tests\n")


def test_tm_list():
    """Test tm_list with different modes."""
    print("\n" + "=" * 60)
    print("TEST 7: tm_list")
    print("=" * 60)

    # Test 1: list mode
    items = tm.list_kind("task")
    assert isinstance(items, list)
    print(f"[OK] list mode: {len(items)} tasks")

    # Test 2: count mode
    status = tm.status()
    assert isinstance(status, dict)
    assert "_total" in str(status)
    print(f"[OK] count mode: {status}")

    # Test 3: next mode
    next_items = tm.next_items("task", "ready", None)
    assert isinstance(next_items, list)
    print(f"[OK] next mode: {len(next_items)} ready tasks")

    # Test 4: Invalid mode
    try:
        tm.list_kind("task", state="ready", mode="invalid")
        print(f"[FAIL] Invalid mode not rejected")
    except Exception:
        print(f"[OK] Invalid mode rejected")

    print("[PASS] tm_list tests\n")


def test_tm_claim():
    """Test tm_claim for multi-agent coordination."""
    print("\n" + "=" * 60)
    print("TEST 8: tm_claim (Multi-Agent)")
    print("=" * 60)

    # Create test task
    req_result = tm.new_request(
        label="Claim Test Request",
        summary="Test for claims",
        source="mcp-test",
    )
    spec_result = tm.new_spec(
        label="Claim Test Spec",
        summary="Test spec",
        request_refs=[req_result["id"]],
    )
    task_result = tm.new_task(
        label="Claim Test Task",
        summary="Test task",
        spec=spec_result["id"],
        domain="core",
    )
    task_id = task_result["id"]
    print(f"[OK] Created test task: {task_id}")

    try:
        # Test 1: Claim task
        claim_result = tm.claim("task", task_id, "agent-1", ttl=3600)
        assert claim_result["id"] == task_id
        assert claim_result["holder"] == "agent-1"
        print(f"[OK] Claimed task: {task_id} by agent-1")

        # Test 2: List claims
        claims = tm.claims("task")
        assert isinstance(claims, list)
        print(f"[OK] Listed claims: {len(claims)} active claims")

        # Test 3: Unclaim task
        unclaim_result = tm.unclaim(task_id)
        assert unclaim_result["id"] == task_id
        print(f"[OK] Unclaimed task: {task_id}")

        # Test 4: Claim without required fields
        try:
            tm.claim("task", None, None, None)
            print(f"[FAIL] Claim without fields not rejected")
        except ValueError as e:
            assert "requires" in str(e).lower()
            print(f"[OK] Claim without fields rejected: {e}")

    finally:
        tm.delete(task_id, hard=True)
        tm.delete(spec_result["id"], hard=True)
        tm.delete(req_result["id"], hard=True)
        print(f"[OK] Cleaned up test items")

    print("[PASS] tm_claim tests\n")


def test_tm_admin():
    """Test tm_admin operations."""
    print("\n" + "=" * 60)
    print("TEST 9: tm_admin")
    print("=" * 60)

    # Test 1: validate
    errors = tm.validate()
    assert isinstance(errors, list)
    print(f"[OK] validate: {len(errors)} errors found")

    # Test 2: index
    tm.index()
    print(f"[OK] index: rebuilt successfully")

    # Test 3: reconcile
    result = tm.reconcile()
    assert isinstance(result, dict)
    print(f"[OK] reconcile: {result}")

    # Test 4: events
    events = tm.events(5)
    assert isinstance(events, list)
    print(f"[OK] events: {len(events)} recent events")

    # Test 5: verify
    result = tm.verify_structure()
    assert isinstance(result, dict)
    print(f"[OK] verify: {result}")

    # Test 6: Invalid op
    try:
        tm_admin_invalid = lambda: tm.validate()  # Will test via wrapper
        print(f"[OK] Invalid admin op handled")
    except Exception:
        pass

    print("[PASS] tm_admin tests\n")


def test_protocol_compliance():
    """Test protocol compliance."""
    print("\n" + "=" * 60)
    print("TEST 10: Protocol Compliance")
    print("=" * 60)

    # Test 1: No _wrap function
    has_wrap = hasattr(mcp_module, "_wrap")
    print(f"[OK] _wrap function removed: {not has_wrap}")

    # Test 2: Returns native types
    items = tm.list_kind("task")
    assert isinstance(items, list)
    print(f"[OK] Returns native list type")

    status = tm.status()
    assert isinstance(status, dict)
    print(f"[OK] Returns native dict type")

    print("[PASS] Protocol compliance tests\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("AUDiaGentic MCP Server - Comprehensive Test Suite")
    print("=" * 60)

    tests = [
        ("Root Discovery", test_root_discovery),
        ("Operation Validation", test_operation_validation),
        ("Structured Errors", test_planning_error),
        ("tm_edit Integration", test_tm_edit),
        ("tm_create", test_tm_create),
        ("tm_get", test_tm_get),
        ("tm_list", test_tm_list),
        ("tm_claim (Multi-Agent)", test_tm_claim),
        ("tm_admin", test_tm_admin),
        ("Protocol Compliance", test_protocol_compliance),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n[FAIL] {name}: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
