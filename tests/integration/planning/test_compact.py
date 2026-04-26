"""Integration tests for deterministic planning ID compaction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.planning_testkit import seed_planning_config

from audiagentic.planning.app.api import PlanningAPI
from audiagentic.planning.app.paths import Paths
from audiagentic.planning.fs.scan import scan_items
from audiagentic.planning.fs.write import dump_markdown


def _seed_planning_project(root: Path) -> None:
    seed_planning_config(root)
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)
    for sub in ("ids", "indexes", "events", "claims", "meta", "extracts"):
        (root / ".audiagentic" / "planning" / sub).mkdir(parents=True, exist_ok=True)


def _item_by_id(root: Path, item_id: str):
    return next(item for item in scan_items(root) if item.data["id"] == item_id)


def test_compact_fills_gap_and_is_idempotent(tmp_path: Path) -> None:
    _seed_planning_project(tmp_path)
    api = PlanningAPI(tmp_path)

    request = api.new("request", label="Compact request", summary="S", source="test")
    api.new("spec", label="Spec one", summary="S", refs={"request_refs": [request.data["id"]]})
    spec_two = api.new("spec", label="Spec two", summary="S", refs={"request_refs": [request.data["id"]]})
    task = api.new("task", label="Task two", summary="S", refs={"spec": spec_two.data["id"]})

    paths = Paths(tmp_path)

    spec_two_item = _item_by_id(tmp_path, spec_two.data["id"])
    spec_two_data = dict(spec_two_item.data)
    spec_two_data["id"] = "spec-3"
    spec_two_new_path = spec_two_item.path.parent / paths.filename_for(
        "spec", "spec-3", spec_two_data["label"]
    )
    dump_markdown(spec_two_item.path, spec_two_data, spec_two_item.body)
    spec_two_item.path.rename(spec_two_new_path)

    task_item = _item_by_id(tmp_path, task.data["id"])
    task_data = dict(task_item.data)
    task_data["spec_ref"] = "spec-3"
    dump_markdown(task_item.path, task_data, task_item.body)

    result = api.compact()

    assert result["aborted"] is False
    assert result["remap"] == {"spec-3": "spec-2"}
    assert {
        entry["category"] for entry in result["cannot_repair"]
    } <= {"validation"}

    compacted_task = _item_by_id(tmp_path, task.data["id"])
    assert compacted_task.data["spec_ref"] == "spec-2"
    assert (tmp_path / "docs" / "planning" / "specifications" / "spec-2-spec-two.md").exists()

    second = api.compact()
    assert second["aborted"] is False
    assert second["already_compact"] is True
    assert second["remapped"] == 0


def test_compact_aborts_on_duplicate_ids(tmp_path: Path) -> None:
    _seed_planning_project(tmp_path)
    api = PlanningAPI(tmp_path)

    request = api.new("request", label="Dup request", summary="S", source="test")
    request_item = _item_by_id(tmp_path, request.data["id"])
    duplicate_path = request_item.path.parent / f"{request.data['id']}-duplicate.md"
    duplicate_path.write_text(request_item.path.read_text(encoding="utf-8"), encoding="utf-8")

    before_original = request_item.path.read_text(encoding="utf-8")
    before_duplicate = duplicate_path.read_text(encoding="utf-8")

    result = api.compact()

    assert result["aborted"] is True
    assert result["remapped"] == 0
    assert result["renames"] == []
    assert any(item["category"] == "duplicate_id" for item in result["cannot_repair"])
    assert request_item.path.read_text(encoding="utf-8") == before_original
    assert duplicate_path.read_text(encoding="utf-8") == before_duplicate
