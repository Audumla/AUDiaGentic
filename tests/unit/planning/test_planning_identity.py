"""Adversarial planning identity and lookup tests."""
from __future__ import annotations

import pytest

from audiagentic.components.planning import planning_api
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
