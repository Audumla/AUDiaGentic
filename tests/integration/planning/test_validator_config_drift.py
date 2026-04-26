from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml
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


def test_validate_allows_plan_reference_fields_and_legacy_ref_lists(tmp_path: Path) -> None:
    _seed_planning_project(tmp_path)
    api = PlanningAPI(tmp_path)

    request = api.new("request", label="R", summary="S", source="test")
    spec = api.new("spec", label="S", summary="S", refs={"request_refs": [request.data["id"]]})

    plan_path = tmp_path / "docs" / "planning" / "plans" / "plan-1-test-plan.md"
    plan_path.write_text(
        "---\n"
        "id: plan-1\n"
        "label: Test Plan\n"
        "state: draft\n"
        "summary: test\n"
        f"request_refs:\n- {request.data['id']}\n"
        f"spec_refs:\n- {spec.data['id']}\n"
        "work_package_refs:\n- ref: wp-1\n  seq: 1000\n"
        "standard_refs:\n- standard-1\n"
        "---\n\n"
        "# Objectives\n\nX\n\n"
        "# Delivery Approach\n\nX\n\n"
        "# Dependencies\n\nX\n",
        encoding="utf-8",
    )

    errors = api.validate()

    assert not any("unknown field 'request_refs'" in e for e in errors)
    assert not any("unknown field 'spec_refs'" in e for e in errors)
    assert not any("unknown field 'work_package_refs'" in e for e in errors)
    assert not any("request_refs must be a list of objects" in e for e in errors)


def test_validate_accepts_spec_request_refs_as_strings(tmp_path: Path) -> None:
    _seed_planning_project(tmp_path)
    api = PlanningAPI(tmp_path)

    request = api.new("request", label="R", summary="S", source="test")
    spec_path = tmp_path / "docs" / "planning" / "specifications" / "spec-1-test-spec.md"
    spec_path.write_text(
        "---\n"
        "id: spec-1\n"
        "label: Test Spec\n"
        "state: draft\n"
        "summary: test\n"
        f"request_refs:\n- {request.data['id']}\n"
        "---\n\n"
        "# Purpose\n\nX\n\n"
        "# Scope\n\nX\n\n"
        "# Requirements\n\nX\n\n"
        "# Constraints\n\nX\n\n"
        "# Acceptance Criteria\n\nX\n",
        encoding="utf-8",
    )

    errors = api.validate()

    assert not any("request_refs must be a list of objects" in e for e in errors)
    assert not any("references non-existent request" in e for e in errors)


def test_validate_uses_configured_downstream_requirements(tmp_path: Path) -> None:
    _seed_planning_project(tmp_path)

    profiles_path = tmp_path / ".audiagentic" / "planning" / "config" / "profiles.yaml"
    profiles = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    profiles["planning"]["relationship_config"]["spec"]["requires_children"]["task"]["states"] = [
        "draft"
    ]
    profiles_path.write_text(yaml.safe_dump(profiles, sort_keys=False), encoding="utf-8")

    api = PlanningAPI(tmp_path)
    request = api.new("request", label="R", summary="S", source="test")
    api.new("spec", label="S", summary="S", refs={"request_refs": [request.data["id"]]})

    errors = api.validate()

    assert any("spec in 'draft' state has no task references" in e for e in errors)


def test_validate_rel_list_string_entries_are_actionable(tmp_path: Path) -> None:
    _seed_planning_project(tmp_path)
    api = PlanningAPI(tmp_path)

    request = api.new("request", label="R", summary="S", source="test")
    spec = api.new("spec", label="S", summary="S", refs={"request_refs": [request.data["id"]]})
    plan = api.new("plan", label="P", summary="S", refs={"spec": spec.data["id"]})

    wp_path = tmp_path / "docs" / "planning" / "work-packages" / "core" / "wp-999-bad.md"
    wp_path.write_text(
        "---\n"
        "id: wp-999\n"
        "label: Bad\n"
        "state: draft\n"
        "summary: bad\n"
        f"plan_ref: {plan.data['id']}\n"
        "task_refs:\n- task-1\n"
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

    assert any("task_refs must be a list of objects with 'ref'" in e for e in errors)
