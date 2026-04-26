"""Integration tests for current planning ID lookup behavior.

IDs now use raw integers as their canonical stored form. Lookup should resolve
exact raw IDs and reject legacy padded aliases.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from tests.planning_testkit import seed_planning_config


def _seed(root: Path) -> None:
    seed_planning_config(root)
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "tasks/contrib",
        "work-packages/core",
        "work-packages/contrib",
        "standards",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)
    for sub in ("ids", "indexes", "events", "claims", "meta", "extracts"):
        (root / ".audiagentic" / "planning" / sub).mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def pr(tmp_path: Path):
    _seed(tmp_path)
    from audiagentic.planning.app.api import PlanningAPI

    return tmp_path, PlanningAPI(tmp_path)


def _new_request(api, label: str) -> object:
    return api.new("request", label=label, summary=f"{label} summary", source="test")


def _request_20(api):
    req = None
    for n in range(1, 21):
        req = _new_request(api, f"Request {n}")
    return req


def _full_hierarchy(api):
    req = _new_request(api, "Request 1")
    spec = api.new("spec", label="Spec 1", summary="Spec summary", refs={"request_refs": [req.data["id"]]})
    plan = api.new("plan", label="Plan 1", summary="Plan summary", refs={"spec": spec.data["id"]})
    task = api.new("task", label="Task 1", summary="Task summary", refs={"spec": spec.data["id"]})
    wp = api.new("wp", label="WP 1", summary="WP summary", refs={"plan": plan.data["id"]})
    return req, spec, plan, task, wp


class TestRequestLookup:
    def test_lookup_exact_raw_request_id(self, pr):
        _, api = pr
        req = _request_20(api)

        item = api.lookup("request-20")

        assert item.kind == "request"
        assert item.data["id"] == req.data["id"] == "request-20"

    def test_lookup_legacy_padded_request_id_fails(self, pr):
        _, api = pr
        _request_20(api)

        with pytest.raises(ValueError) as exc_info:
            api.lookup("request-020")

        error_msg = str(exc_info.value)
        assert "request-020 not found" in error_msg
        assert "tried exact match" in error_msg
        assert "Closest: request-20" in error_msg

    def test_lookup_single_digit_request_uses_raw_id(self, pr):
        _, api = pr
        req = _new_request(api, "Request 1")

        item = api.lookup("request-1")

        assert item.kind == "request"
        assert item.data["id"] == req.data["id"] == "request-1"

    def test_lookup_legacy_single_digit_padded_request_id_fails(self, pr):
        _, api = pr
        _new_request(api, "Request 1")

        with pytest.raises(ValueError) as exc_info:
            api.lookup("request-001")

        error_msg = str(exc_info.value)
        assert "request-001 not found" in error_msg
        assert "Closest: request-1" in error_msg


class TestOtherKindsLookup:
    def test_lookup_exact_raw_ids_across_item_kinds(self, pr):
        _, api = pr
        req, spec, plan, task, wp = _full_hierarchy(api)

        assert api.lookup(req.data["id"]).data["id"] == "request-1"
        assert api.lookup(spec.data["id"]).data["id"] == "spec-1"
        assert api.lookup(plan.data["id"]).data["id"] == "plan-1"
        assert api.lookup(task.data["id"]).data["id"] == "task-1"
        assert api.lookup(wp.data["id"]).data["id"] == "wp-1"

    @pytest.mark.parametrize(
        ("legacy_id", "closest"),
        [
            ("spec-001", "spec-1"),
            ("plan-001", "plan-1"),
            ("task-0001", "task-1"),
            ("wp-001", "wp-1"),
        ],
    )
    def test_lookup_legacy_padded_ids_fail_for_other_kinds(self, pr, legacy_id: str, closest: str):
        _, api = pr
        _full_hierarchy(api)

        with pytest.raises(ValueError) as exc_info:
            api.lookup(legacy_id)

        error_msg = str(exc_info.value)
        assert f"{legacy_id} not found" in error_msg
        assert "tried exact match" in error_msg
        assert f"Closest: {closest}" in error_msg


class TestErrorMessages:
    def test_error_shows_available_items_for_current_ids(self, pr):
        _, api = pr
        _request_20(api)

        with pytest.raises(ValueError) as exc_info:
            api.lookup("request-999")

        error_msg = str(exc_info.value)
        assert "Available" in error_msg
        assert "tm_list with the relevant kind" in error_msg
        assert "request-20" in error_msg

    def test_error_no_longer_reports_normalized_id_attempt(self, pr):
        _, api = pr
        _request_20(api)

        with pytest.raises(ValueError) as exc_info:
            api.lookup("request-099")

        error_msg = str(exc_info.value)
        assert "tried exact match" in error_msg
        assert "request-99" not in error_msg
