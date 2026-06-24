"""Unit tests for planning_api — isolated, pure filesystem via tmp_path.

planning_paths falls back to _DEFAULT_PATHS when the features registry is not
populated, so these tests need no mocking of the paths layer.
"""
from __future__ import annotations

import pytest

from audiagentic.components.planning import planning_api, planning_paths
from audiagentic.foundation.contracts.errors import AudiaGenticError

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_item(**kwargs) -> dict:
    base = {"id": "TST01", "plan": "test-plan", "title": "Test item"}
    base.update(kwargs)
    return base


def _active_dir(root):
    return planning_paths.plans_active_dir(root)


def _completed_dir(root):
    return planning_paths.plans_completed_dir(root)


# ---------------------------------------------------------------------------
# create_item
# ---------------------------------------------------------------------------

def test_create_item_writes_file_in_active_dir(tmp_path):
    result = planning_api.create_item(tmp_path, _make_item())

    assert result["ok"] is True
    assert result["id"] == "TST01"
    target = tmp_path / result["path"]
    assert target.exists()
    assert _active_dir(tmp_path) in target.parents


def test_create_item_frontmatter_state_is_pending(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    path = _active_dir(tmp_path) / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    assert "state: pending" in text


def test_create_item_frontmatter_has_plan_prefix(tmp_path):
    planning_api.create_item(tmp_path, _make_item(plan="test-plan"))
    path = _active_dir(tmp_path) / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    assert "plan: plan-test-plan" in text


def test_create_item_plan_prefix_not_doubled(tmp_path):
    planning_api.create_item(tmp_path, _make_item(plan="plan-test-plan"))
    path = _active_dir(tmp_path) / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    assert "plan: plan-test-plan" in text
    assert "plan-plan-" not in text


def test_create_item_body_contains_title_heading(tmp_path):
    planning_api.create_item(tmp_path, _make_item(title="My Feature"))
    path = _active_dir(tmp_path) / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    assert "# My Feature" in text


def test_create_item_body_contains_standard_sections(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    path = _active_dir(tmp_path) / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    for heading in ("## Description", "## Steps", "## Files", "## Validation", "## Effort & Risk", "## Notes"):
        assert heading in text, f"missing section {heading!r}"


def test_create_item_missing_id_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_item(tmp_path, {"plan": "p", "title": "t"})
    assert exc_info.value.code == "VAL-PLN-002"


def test_create_item_missing_plan_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_item(tmp_path, {"id": "X01", "title": "t"})
    assert exc_info.value.code == "VAL-PLN-003"


def test_create_item_missing_title_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_item(tmp_path, {"id": "X01", "plan": "p"})
    assert exc_info.value.code == "VAL-PLN-004"


def test_create_item_duplicate_raises(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_item(tmp_path, _make_item())
    assert exc_info.value.code == "VAL-PLN-005"


def test_create_item_optional_fields_in_frontmatter(tmp_path):
    planning_api.create_item(tmp_path, _make_item(priority="P0", complexity="complex", order=3))
    path = _active_dir(tmp_path) / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    assert "priority: P0" in text
    assert "complexity: complex" in text
    assert "order: 3" in text


# ---------------------------------------------------------------------------
# list_items
# ---------------------------------------------------------------------------

def test_list_items_empty_returns_empty(tmp_path):
    assert planning_api.list_items(tmp_path) == []


def test_list_items_returns_created_item(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    items = planning_api.list_items(tmp_path)
    assert len(items) == 1
    assert items[0]["id"] == "TST01"
    assert items[0]["title"] == "Test item"


def test_list_items_active_filter_excludes_completed(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="A01"))
    planning_api.create_item(tmp_path, _make_item(id="A02"))
    planning_api.set_state(tmp_path, "A01", "completed")

    items = planning_api.list_items(tmp_path, state="active")
    ids = [i["id"] for i in items]
    assert "A02" in ids
    assert "A01" not in ids


def test_list_items_completed_filter_returns_only_completed(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="B01"))
    planning_api.create_item(tmp_path, _make_item(id="B02"))
    planning_api.set_state(tmp_path, "B01", "completed")

    items = planning_api.list_items(tmp_path, state="completed")
    assert len(items) == 1
    assert items[0]["id"] == "B01"


def test_list_items_plan_filter_returns_only_matching_plan(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="C01", plan="alpha"))
    planning_api.create_item(tmp_path, _make_item(id="C02", plan="beta"))

    items = planning_api.list_items(tmp_path, plan="alpha")
    assert len(items) == 1
    assert items[0]["id"] == "C01"


def test_list_items_no_filter_returns_all(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="D01"))
    planning_api.create_item(tmp_path, _make_item(id="D02"))
    planning_api.set_state(tmp_path, "D01", "completed")

    items = planning_api.list_items(tmp_path)
    ids = {i["id"] for i in items}
    assert ids == {"D01", "D02"}


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------

def test_get_item_returns_frontmatter_and_sections(tmp_path):
    planning_api.create_item(tmp_path, _make_item(description="Do the thing."))
    item = planning_api.get_item(tmp_path, "TST01")

    assert item["id"] == "TST01"
    assert item["state"] == "pending"
    assert item["title"] == "Test item"
    assert item["description"] == "Do the thing."


def test_get_item_not_found_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.get_item(tmp_path, "MISSING01")
    assert exc_info.value.code == "VAL-PLN-001"


# ---------------------------------------------------------------------------
# set_state
# ---------------------------------------------------------------------------

def test_set_state_pending_to_completed_moves_file(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    result = planning_api.set_state(tmp_path, "TST01", "completed")

    assert result["ok"] is True
    assert result["state"] == "completed"
    assert not (_active_dir(tmp_path) / "test-plan" / "TST01.md").exists()
    assert (_completed_dir(tmp_path) / "test-plan" / "TST01.md").exists()


def test_set_state_updates_frontmatter_state(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.set_state(tmp_path, "TST01", "completed")

    text = (_completed_dir(tmp_path) / "test-plan" / "TST01.md").read_text(encoding="utf-8")
    assert "state: completed" in text


def test_set_state_completed_to_pending_moves_back(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.set_state(tmp_path, "TST01", "completed")
    result = planning_api.set_state(tmp_path, "TST01", "pending")

    assert result["state"] == "pending"
    assert (_active_dir(tmp_path) / "test-plan" / "TST01.md").exists()
    assert not (_completed_dir(tmp_path) / "test-plan" / "TST01.md").exists()


def test_set_state_not_done_alias_moves_to_active(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.set_state(tmp_path, "TST01", "completed")
    result = planning_api.set_state(tmp_path, "TST01", "not_done")

    assert result["state"] == "pending"
    assert (_active_dir(tmp_path) / "test-plan" / "TST01.md").exists()


def test_set_state_invalid_state_raises(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.set_state(tmp_path, "TST01", "in_progress")
    assert exc_info.value.code == "VAL-PLN-006"


def test_set_state_not_found_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.set_state(tmp_path, "GHOST01", "completed")
    assert exc_info.value.code == "VAL-PLN-001"


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------

def test_update_item_updates_frontmatter_field(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    result = planning_api.update_item(tmp_path, "TST01", {"priority": "P0"})

    assert result["ok"] is True
    item = planning_api.get_item(tmp_path, "TST01")
    assert item["priority"] == "P0"


def test_update_item_updates_body_section(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.update_item(tmp_path, "TST01", {"description": "Updated description."})

    item = planning_api.get_item(tmp_path, "TST01")
    assert item["description"] == "Updated description."


def test_update_item_updates_title(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.update_item(tmp_path, "TST01", {"title": "New Title"})

    item = planning_api.get_item(tmp_path, "TST01")
    assert item["title"] == "New Title"


def test_update_item_preserves_unchanged_fields(tmp_path):
    planning_api.create_item(tmp_path, _make_item(priority="P1"))
    planning_api.update_item(tmp_path, "TST01", {"complexity": "complex"})

    item = planning_api.get_item(tmp_path, "TST01")
    assert item["priority"] == "P1"
    assert item["complexity"] == "complex"


def test_update_item_not_found_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.update_item(tmp_path, "GHOST01", {"priority": "P0"})
    assert exc_info.value.code == "VAL-PLN-001"


# ---------------------------------------------------------------------------
# delete_item
# ---------------------------------------------------------------------------

def test_delete_item_removes_file(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    result = planning_api.delete_item(tmp_path, "TST01")

    assert result["ok"] is True
    assert not (_active_dir(tmp_path) / "test-plan" / "TST01.md").exists()


def test_delete_item_completed_item_removes_file(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.set_state(tmp_path, "TST01", "completed")
    planning_api.delete_item(tmp_path, "TST01")

    assert not (_completed_dir(tmp_path) / "test-plan" / "TST01.md").exists()


def test_delete_item_not_found_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.delete_item(tmp_path, "GHOST01")
    assert exc_info.value.code == "VAL-PLN-001"


def test_delete_item_then_list_returns_empty(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.delete_item(tmp_path, "TST01")
    assert planning_api.list_items(tmp_path) == []
