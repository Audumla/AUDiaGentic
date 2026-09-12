"""Adversarial planning identity and lookup tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.planning import planning_api, planning_paths
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.mark.parametrize("plan", ["../escape", "code/*", "Code-Cleanup", "code cleanup"])
def test_create_item_rejects_unsafe_plan_slug(tmp_path, plan):
    with pytest.raises(AudiaGenticError):
        planning_api.create_item(tmp_path, {"plan": plan, "title": "bad"})


@pytest.mark.parametrize("item_id", ["../X01", "X*", "x01", "RV01"])
def test_create_item_rejects_unsafe_item_id(tmp_path, item_id):
    with pytest.raises(AudiaGenticError):
        planning_api.create_item(tmp_path, {"id": item_id, "plan": "safe-plan", "title": "bad"})


def test_create_review_requires_rv_id(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "safe-plan", "title": "item"})
    with pytest.raises(AudiaGenticError):
        planning_api.create_review(
            tmp_path, {"id": "OTHER01", "review-of": "ITM01", "title": "bad"}
        )


def test_plan_filter_is_not_a_glob(tmp_path):
    planning_api.create_item(tmp_path, {"id": "A01", "plan": "code-cleanup", "title": "item"})
    with pytest.raises(AudiaGenticError):
        planning_api.list_items(tmp_path, plan="code-*")


def test_lookup_ignores_stray_nested_record_with_matching_stem(tmp_path):
    planning_api.create_item(tmp_path, {"id": "X01", "plan": "safe-plan", "title": "item"})
    stray = tmp_path / "docs" / "planning" / "active" / "safe-plan" / "nested" / "X01.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("not a canonical item", encoding="utf-8")

    assert planning_api.get_item(tmp_path, "X01")["title"] == "item"


def test_resolved_planning_path_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "planning"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(AudiaGenticError, match="VAL-PLN-038"):
        planning_paths.assert_contained(root, link / "escape.md")
