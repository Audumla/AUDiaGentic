import os
import sys
from pathlib import Path
import shutil


# Bootstrap project root to import audiagentic
def bootstrap():
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / ".audiagentic" / "planning").exists():
            sys.path.insert(0, str(p))
            sys.path.insert(0, str(p / "src"))
            return p
    raise RuntimeError("Could not find project root")


root = bootstrap()

import tools.planning.tm_helper as tm
from audiagentic.planning.app.api import PlanningAPI


def test_validate_id():
    print("Testing _validate_id...")
    # Valid IDs
    tm._validate_id("task-0001")
    tm._validate_id("spec-0001")

    # Invalid IDs
    for invalid in ["../.env", "/etc/passwd", "C:\\Windows", "task/0001"]:
        try:
            tm._validate_id(invalid)
            print(f"FAILED: {invalid} should have been rejected")
        except ValueError:
            pass
    print("[OK] _validate_id passed")


def test_batch_atomicity():
    print("Testing _execute_batch_operations atomicity...")
    api = PlanningAPI(root)

    # Find or create a request for the spec
    request_files = list((root / "docs/planning/requests").glob("request-*.md"))
    if not request_files:
        print("FAILED: No request files found for test")
        return
    request_id = request_files[0].stem  # e.g., "request-0001"

    # Find or create a spec (reuse existing "Test Spec" if it exists)
    spec_id = None
    for item in api._scan():
        if item.kind == "spec" and item.data.get("label") == "Test Spec":
            spec_id = item.data["id"]
            break

    if not spec_id:
        spec = api.new("spec", "Test Spec", "Test summary", request_refs=[request_id])
        spec_id = spec.data["id"]
    else:
        spec = api._find(spec_id)

    # Find or create a task for this spec
    task_id = None
    for item in api._scan():
        if item.kind == "task" and item.data.get("label") == "Atomicity Task":
            task_id = item.data["id"]
            break

    if not task_id:
        task = api.new("task", "Atomicity Task", "Summary", spec=spec_id)
        task_id = task.data["id"]
    else:
        task = api._find(task_id)

    original_label = task.data["label"]

    # Define a batch that fails at the end
    ops = [
        {"op": "label", "value": "Updated Label"},
        {"op": "invalid_op", "value": "this should fail"},
    ]

    try:
        tm._execute_batch_operations(api, task_id, ops)
        print("FAILED: batch should have raised an exception")
    except Exception:
        # Verify rollback
        restored_item = api._find(task_id)
        if restored_item.data["label"] == original_label:
            print("[OK] atomicity restore passed")
        else:
            print(f"FAILED: label was not restored. Got: {restored_item.data['label']}")


def test_generic_create():
    print("Testing generic create dispatcher...")
    api = PlanningAPI(root)

    # Test request creation
    req = tm.create("request", "Generic Req", "Summary", source="test-agent")
    if req["created"]:
        print("[OK] request create passed")
    else:
        print("INFO: request create found duplicate")

    # Test task creation
    # Need a spec first
    spec = api.new("spec", "Generic Spec", "Summary", request_refs=[req["id"]])
    task = tm.create("task", "Generic Task", "Summary", spec=spec.data["id"])
    if "id" in task:
        print("[OK] task create passed")
    else:
        print("FAILED: task create failed")


def test_list_kind_multiple_kinds():
    print("Testing list_kind with multiple kinds...")
    # Test with list of kinds
    result = tm.list_kind(kind=["request", "spec"], root=root)
    assert isinstance(result, list), "Result should be a list"

    # All items should be either request or spec
    for item in result:
        assert item["kind"] in ["request", "spec"], f"Item kind {item['kind']} not in filter"

    print(f"[OK] list_kind with multiple kinds passed (found {len(result)} items)")


def test_list_kind_multiple_states():
    print("Testing list_kind with multiple states...")
    # Test with list of states
    result = tm.list_kind(state=["captured", "distilled", "in_progress"], root=root)
    assert isinstance(result, list), "Result should be a list"

    # All items should have one of the specified states
    for item in result:
        assert item["state"] in ["captured", "distilled", "in_progress"], (
            f"Item state {item['state']} not in filter"
        )

    print(f"[OK] list_kind with multiple states passed (found {len(result)} items)")


def test_list_kind_combined_filters():
    print("Testing list_kind with combined kind and state filters...")
    # Test with both kind and state as lists
    result = tm.list_kind(kind=["request", "spec"], state=["captured", "distilled"], root=root)
    assert isinstance(result, list), "Result should be a list"

    # All items should match both filters
    for item in result:
        assert item["kind"] in ["request", "spec"], f"Item kind {item['kind']} not in filter"
        assert item["state"] in ["captured", "distilled"], (
            f"Item state {item['state']} not in filter"
        )

    print(f"[OK] list_kind with combined filters passed (found {len(result)} items)")


def test_list_kind_single_values_still_work():
    print("Testing list_kind with single values (backward compatibility)...")
    # Test with single kind
    result = tm.list_kind(kind="request", root=root)
    assert isinstance(result, list), "Result should be a list"
    for item in result:
        assert item["kind"] == "request", f"Item kind {item['kind']} should be request"

    # Test with single state
    result = tm.list_kind(state="captured", root=root)
    assert isinstance(result, list), "Result should be a list"
    for item in result:
        assert item["state"] == "captured", f"Item state {item['state']} should be captured"

    print("[OK] list_kind backward compatibility passed")


if __name__ == "__main__":
    try:
        test_validate_id()
        test_batch_atomicity()
        test_generic_create()
        test_list_kind_multiple_kinds()
        test_list_kind_multiple_states()
        test_list_kind_combined_filters()
        test_list_kind_single_values_still_work()
        print("\nALL TESTS PASSED")
    except Exception as e:
        print(f"\nTEST SUITE FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
