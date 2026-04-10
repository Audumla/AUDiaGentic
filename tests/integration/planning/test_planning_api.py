"""Integration tests for PlanningAPI against a real temp-dir project."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT = Path(__file__).resolve().parents[3]
PLANNING_CONFIG_SRC = ROOT / ".audiagentic" / "planning" / "config"


def _seed_planning_project(root: Path) -> None:
    """Seed the minimum planning config needed for PlanningAPI."""
    config_dir = root / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, config_dir / f.name)
    # Seed doc directories
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def planning_root(tmp_path: Path):
    _seed_planning_project(tmp_path)
    from audiagentic.planning.app.api import PlanningAPI

    return tmp_path, PlanningAPI(tmp_path)


def test_validate_empty_project(planning_root):
    _, api = planning_root
    errors = api.validate()
    assert errors == []


def test_new_request(planning_root):
    root, api = planning_root
    item = api.new("request", label="Test request", summary="A test", source="test")
    assert item.data["id"] == "request-0001"
    assert item.data["state"] == "captured"
    assert (root / "docs" / "planning" / "requests" / "request-0001.md").exists()


def test_new_request_persists_source_and_context(planning_root):
    _, api = planning_root
    item = api.new(
        "request",
        label="Traceable request",
        summary="A test",
        source="mcp",
        context="codex review session",
    )
    assert item.data["source"] == "mcp"
    assert item.data["context"] == "codex review session"


def test_new_spec_and_task(planning_root):
    _, api = planning_root
    spec = api.new("spec", label="My spec", summary="Spec summary")
    task = api.new(
        "task", label="Do the thing", summary="Task summary", spec=spec.data["id"]
    )
    assert spec.data["id"] == "spec-0001"
    assert task.data["id"] == "task-0001"
    assert task.data["spec_ref"] == "spec-0001"


def test_state_transition(planning_root):
    _, api = planning_root
    spec = api.new("spec", label="S", summary="S")
    item = api.state(spec.data["id"], "ready")
    assert item.data["state"] == "ready"


def test_invalid_state_transition_rejected(planning_root):
    _, api = planning_root
    spec = api.new("spec", label="S", summary="S")
    with pytest.raises(ValueError, match="invalid transition"):
        api.state(spec.data["id"], "done")  # draft → done not allowed


def test_id_counter_persisted_across_api_instances(planning_root):
    root, api = planning_root
    api.new("request", label="R1", summary="S", source="test")
    api.new("request", label="R2", summary="S", source="test")
    # New API instance should continue from counter
    from audiagentic.planning.app.api import PlanningAPI

    api2 = PlanningAPI(root)
    item = api2.new("request", label="R3", summary="S", source="test")
    assert item.data["id"] == "request-0003"


def test_index_creates_files(planning_root):
    root, api = planning_root
    api.new("request", label="R", summary="S", source="test")
    api.index()
    idx = root / ".audiagentic" / "planning" / "indexes"
    assert (idx / "requests.json").exists()
    assert (idx / "trace.json").exists()
    assert (idx / "dispatch.json").exists()


def test_dispatch_json_initialised_by_index(planning_root):
    root, api = planning_root
    api.index()
    dispatch = json.loads(
        (root / ".audiagentic" / "planning" / "indexes" / "dispatch.json").read_text()
    )
    assert "entries" in dispatch


def test_validate_catches_duplicate_ids(planning_root):
    root, api = planning_root
    api.new("request", label="R", summary="S", source="test")
    # Manually write a duplicate
    dup = root / "docs" / "planning" / "requests" / "request-0001-dup.md"
    dup.write_text(
        "---\n"
        "id: request-0001\n"
        "label: Dup\n"
        "state: captured\n"
        "summary: dup\n"
        "current_understanding: dup\n"
        "open_questions: []\n"
        "---\n"
        "# Understanding\n\nDup\n\n"
        "# Open Questions\n\n- None\n\n"
        "# Notes\n\n",
        encoding="utf-8",
    )
    errors = api.validate()
    assert any("duplicate id" in e for e in errors)


def test_claims_roundtrip(planning_root):
    _, api = planning_root
    task = api.new(
        "task",
        label="T",
        summary="S",
        spec=api.new("spec", label="S", summary="S").data["id"],
    )
    rec = api.claim("task", task.data["id"], holder="agent-1", ttl=60)
    assert rec["holder"] == "agent-1"
    active = api.claims("task")
    assert any(c["id"] == task.data["id"] for c in active)
    assert api.unclaim(task.data["id"])
    assert api.claims("task") == []


def test_next_items_excludes_claimed(planning_root):
    _, api = planning_root
    spec = api.new("spec", label="S", summary="S")
    task = api.new("task", label="T", summary="S", spec=spec.data["id"])
    api.state(task.data["id"], "ready")
    api.claim("task", task.data["id"], holder="agent-1")
    assert api.next_items("task", "ready") == []


def test_package_creates_wp_with_task_refs(planning_root):
    _, api = planning_root
    spec = api.new("spec", label="S", summary="S")
    plan = api.new("plan", label="P", summary="P", spec=spec.data["id"])
    task = api.new("task", label="T", summary="S", spec=spec.data["id"])
    wp = api.package(plan.data["id"], [task.data["id"]], label="WP", summary="S")
    assert any(r["ref"] == task.data["id"] for r in wp.data["task_refs"])


def test_api_new_plan_and_task_preserve_request_trace_in_index(planning_root):
    root, api = planning_root
    request = api.new("request", label="R", summary="Request summary", source="test")
    spec = api.new(
        "spec",
        label="S",
        summary="Spec summary",
        request_refs=[request.data["id"]],
    )
    plan = api.new(
        "plan",
        label="P",
        summary="Plan summary",
        spec=spec.data["id"],
        request_refs=[request.data["id"]],
    )
    task = api.new(
        "task",
        label="T",
        summary="Task summary",
        spec=spec.data["id"],
        request_refs=[request.data["id"]],
    )
    trace = json.loads(
        (root / ".audiagentic" / "planning" / "indexes" / "trace.json").read_text(
            encoding="utf-8"
        )
    )
    request_edges = [
        ref
        for ref in trace["refs"]
        if ref["field"] == "request_refs" and ref["dst"] == request.data["id"]
    ]
    assert any(ref["src"] == spec.data["id"] for ref in request_edges)
    assert any(ref["src"] == plan.data["id"] for ref in request_edges)
    assert any(ref["src"] == task.data["id"] for ref in request_edges)


def test_api_duplicate_detection_rejects_duplicate_requests_and_specs(planning_root):
    _, api = planning_root
    api.new("request", label="Repeated request", summary="Same summary", source="test")
    with pytest.raises(ValueError, match="request already exists"):
        api.new("request", label="Repeated request", summary="Same summary", source="test")

    api.new("spec", label="Repeated spec", summary="Spec summary")
    with pytest.raises(ValueError, match="spec already exists"):
        api.new("spec", label="Repeated spec", summary="Spec summary")


def test_api_delete_soft_and_hard(planning_root):
    _, api = planning_root
    spec = api.new("spec", label="S", summary="S")
    task = api.new("task", label="Delete me", summary="S", spec=spec.data["id"])

    soft = api.delete(task.data["id"], reason="cleanup")
    shown = api.extracts.show(task.data["id"])
    assert soft["hard_delete"] is False
    assert shown["deleted"] is True
    assert shown["deletion_reason"] == "cleanup"

    hard = api.delete(task.data["id"], hard=True, reason="cleanup")
    assert hard["hard_delete"] is True
    with pytest.raises(KeyError):
        api._find(task.data["id"])

    next_task = api.new("task", label="Next task", summary="S", spec=spec.data["id"])
    assert next_task.data["id"] == "task-0002"


def test_validation_error_messages_are_actionable(planning_root):
    root, api = planning_root
    spec = api.new("spec", label="S", summary="S")
    plan = api.new("plan", label="P", summary="P", spec=spec.data["id"])
    wp_path = root / "docs" / "planning" / "work-packages" / "core" / "wp-9999-bad.md"
    wp_path.write_text(
        "---\n"
        "id: wp-9999\n"
        "label: Bad\n"
        "state: draft\n"
        "summary: bad\n"
        f"plan_ref: {plan.data['id']}\n"
        "task_refs:\n"
        "- task-0001\n"
        "---\n\n"
        "# Objective\n\nX\n\n"
        "# Scope of This Package\n\nX\n\n"
        "# Inputs\n\nX\n\n"
        "# Instructions\n\nX\n\n"
        "# Required Outputs\n\nX\n\n"
        "# Acceptance Checks\n\nX\n\n"
        "# Non-Goals\n\nX\n",
        encoding="utf-8",
    )

    errors = api.validate()
    assert any(
        "task_refs must be a list of objects with 'ref'" in error for error in errors
    )


def test_package_tasks_to_existing_wp_not_duplicate(planning_root):
    """Regression: tm_package should add tasks to existing WP, not create duplicate."""
    root, api = planning_root
    spec = api.new("spec", label="S", summary="S")
    plan = api.new("plan", label="P", summary="P", spec=spec.data["id"])

    # Create a work package manually
    wp = api.new("wp", label="Test WP", summary="Test", plan=plan.data["id"])
    wp_id = wp.data["id"]

    # Create some tasks
    task1 = api.new("task", label="T1", summary="S", spec=spec.data["id"])
    task2 = api.new("task", label="T2", summary="S", spec=spec.data["id"])

    # Package tasks to the existing WP
    result = api.package(
        plan.data["id"],
        [task1.data["id"], task2.data["id"]],
        label="Test WP",
        summary="Test",
    )

    # Should return the existing WP, not create a new one
    assert result.data["id"] == wp_id

    # Verify tasks are in the WP
    wp_item = api._find(wp_id)
    from audiagentic.planning.fs.read import parse_markdown

    data, _ = parse_markdown(wp_item.path)
    task_refs = data.get("task_refs", [])
    assert len(task_refs) == 2
    assert any(t.get("ref") == task1.data["id"] for t in task_refs)
    assert any(t.get("ref") == task2.data["id"] for t in task_refs)

    # Verify no duplicate WP was created
    all_wps = list(
        (root / "docs" / "planning" / "work-packages" / "core").glob("wp-*.md")
    )
    assert len(all_wps) == 1
