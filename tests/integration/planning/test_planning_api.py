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
    for d in ("requests", "specifications", "plans", "tasks/core", "work-packages/core", "standards"):
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
    item = api.new("request", label="Test request", summary="A test")
    assert item.data["id"] == "request-0001"
    assert item.data["state"] == "captured"
    assert (root / "docs" / "planning" / "requests" / "request-0001.md").exists()


def test_new_spec_and_task(planning_root):
    _, api = planning_root
    spec = api.new("spec", label="My spec", summary="Spec summary")
    task = api.new("task", label="Do the thing", summary="Task summary", spec=spec.data["id"])
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
    api.new("request", label="R1", summary="S")
    api.new("request", label="R2", summary="S")
    # New API instance should continue from counter
    from audiagentic.planning.app.api import PlanningAPI
    api2 = PlanningAPI(root)
    item = api2.new("request", label="R3", summary="S")
    assert item.data["id"] == "request-0003"


def test_index_creates_files(planning_root):
    root, api = planning_root
    api.new("request", label="R", summary="S")
    api.index()
    idx = root / ".audiagentic" / "planning" / "indexes"
    assert (idx / "requests.json").exists()
    assert (idx / "trace.json").exists()
    assert (idx / "dispatch.json").exists()


def test_dispatch_json_initialised_by_index(planning_root):
    root, api = planning_root
    api.index()
    dispatch = json.loads((root / ".audiagentic" / "planning" / "indexes" / "dispatch.json").read_text())
    assert "entries" in dispatch


def test_validate_catches_duplicate_ids(planning_root):
    root, api = planning_root
    api.new("request", label="R", summary="S")
    # Manually write a duplicate
    dup = root / "docs" / "planning" / "requests" / "request-0001-dup.md"
    dup.write_text("---\nid: request-0001\nlabel: Dup\nstate: captured\nsummary: dup\n---\n# Notes\n\n", encoding="utf-8")
    errors = api.validate()
    assert any("duplicate id" in e for e in errors)


def test_claims_roundtrip(planning_root):
    _, api = planning_root
    task = api.new("task", label="T", summary="S",
                   spec=api.new("spec", label="S", summary="S").data["id"])
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
