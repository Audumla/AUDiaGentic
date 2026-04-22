from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from tests.planning_testkit import seed_planning_config

from audiagentic.planning.app.api import PlanningAPI


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
