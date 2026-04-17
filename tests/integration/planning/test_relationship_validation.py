from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from audiagentic.planning.app.api import PlanningAPI

ROOT = Path(__file__).resolve().parents[3]
PLANNING_CONFIG_SRC = ROOT / ".audiagentic" / "planning" / "config"


def _seed_planning_project(root: Path) -> None:
    config_dir = root / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, config_dir / f.name)
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def planning_api(tmp_path: Path) -> PlanningAPI:
    _seed_planning_project(tmp_path)
    return PlanningAPI(tmp_path)


def _make_request_spec_plan(api: PlanningAPI) -> tuple[str, str, str]:
    request = api.new("request", label="Req", summary="Req", source="test")
    spec = api.new("spec", label="Spec", summary="Spec", request_refs=[request.data["id"]])
    plan = api.new("plan", label="Plan", summary="Plan", spec=spec.data["id"])
    return request.data["id"], spec.data["id"], plan.data["id"]


def test_task_parent_must_reference_task(planning_api: PlanningAPI) -> None:
    request_id, spec_id, _ = _make_request_spec_plan(planning_api)

    with pytest.raises(
        ValueError,
        match=r"Invalid reference .*parent_task_ref.*expected \['task'\]",
    ):
        planning_api.new(
            "task",
            label="Bad Parent",
            summary="Bad Parent",
            spec=spec_id,
            parent=request_id,
        )


def test_standard_refs_must_reference_standard(planning_api: PlanningAPI) -> None:
    request_id, _, _ = _make_request_spec_plan(planning_api)

    with pytest.raises(
        ValueError,
        match=r"Invalid reference .*standard_refs.*expected \['standard'\]",
    ):
        planning_api.new(
            "spec",
            label="Bad Standard Ref",
            summary="Bad Standard Ref",
            request_refs=[request_id],
            standard_refs=[request_id],
        )


def test_wp_create_still_allows_deferred_task_linking(planning_api: PlanningAPI) -> None:
    _, _, plan_id = _make_request_spec_plan(planning_api)

    wp = planning_api.new("wp", label="Loose WP", summary="Loose WP", plan=plan_id)

    assert wp.data["id"].startswith("wp-")
