"""Unit tests for planning_api — isolated, pure filesystem via tmp_path.

planning_paths falls back to _DEFAULT_PATHS when the features registry is not
populated, so these tests need no mocking of the paths layer.
"""
from __future__ import annotations

import pytest

from audiagentic.components.planning import events as planning_events
from audiagentic.components.planning import planning_api, planning_paths
from audiagentic.foundation.contracts.errors import AudiaGenticError

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_item(**kwargs) -> dict:
    base = {"id": "TST01", "plan": "test-plan", "title": "Test item", "created-by": "agent"}
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

    assert result["id"] == "TST01"
    assert result["title"] == "Test item"
    assert result["plan"] == "test-plan"
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


def test_create_item_auto_generates_id(tmp_path):
    result = planning_api.create_item(tmp_path, {"plan": "p", "title": "t"})
    assert result["id"] == "P01"
    assert result["title"] == "t"
    item = planning_api.get_item(tmp_path, "P01")
    assert item["id"] == "P01"


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


def test_create_item_records_creator_identity(tmp_path):
    planning_api.create_item(tmp_path, _make_item(**{"created-by": "codex"}))
    item = planning_api.get_item(tmp_path, "TST01")
    listed = planning_api.list_items(tmp_path)

    assert item["created-by"] == "codex"
    assert listed[0]["created-by"] == "codex"


def test_create_item_event_includes_creator_identity(tmp_path, monkeypatch):
    published = []
    monkeypatch.setattr(planning_events, "publish_planning_event", lambda *args, **kwargs: published.append((args, kwargs)))

    planning_api.create_item(tmp_path, _make_item(**{"created-by": "codex"}))

    event_type, payload = published[0][0]
    assert event_type == planning_events.PLANNING_ITEM_CREATED
    assert payload["id"] == "TST01"
    assert payload["created-by"] == "codex"
    assert published[0][1]["subject_id"] == "TST01"


def test_update_item_accepts_creator_identity_alias(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.update_item(tmp_path, "TST01", {"creator_id": "claude"})

    assert planning_api.get_item(tmp_path, "TST01")["created-by"] == "claude"


def test_update_item_event_includes_creator_identity(tmp_path, monkeypatch):
    published = []
    monkeypatch.setattr(planning_events, "publish_planning_event", lambda *args, **kwargs: published.append((args, kwargs)))
    planning_api.create_item(tmp_path, _make_item(created_by="codex"))
    published.clear()

    planning_api.update_item(tmp_path, "TST01", {"creator_id": "claude"})

    event_type, payload = published[0][0]
    assert event_type == planning_events.PLANNING_ITEM_UPDATED
    assert payload["created-by"] == "claude"
    assert payload["updated_keys"] == ["creator_id"]


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


def test_list_items_id_prefix_filter(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="CC01"))
    planning_api.create_item(tmp_path, _make_item(id="CC02"))
    planning_api.create_item(tmp_path, _make_item(id="ML01"))

    items = planning_api.list_items(tmp_path, id_prefix="cc")
    ids = {i["id"] for i in items}
    assert ids == {"CC01", "CC02"}


def test_list_items_plan_wildcard_filter(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="E01", plan="code-cleanup"))
    planning_api.create_item(tmp_path, _make_item(id="E02", plan="code-review"))
    planning_api.create_item(tmp_path, _make_item(id="E03", plan="memory-hindsight"))

    items = planning_api.list_items(tmp_path, plan="code-*")
    ids = {i["id"] for i in items}
    assert ids == {"E01", "E02"}


def test_list_items_page_defaults_to_active_state(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="F01"))
    planning_api.create_item(tmp_path, _make_item(id="F02"))
    planning_api.set_state(tmp_path, "F01", "completed")

    page = planning_api.list_items_page(tmp_path)
    ids = {i["id"] for i in page["items"]}
    assert ids == {"F02"}
    assert page["total"] == 1


def test_list_items_page_state_all_includes_completed(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="G01"))
    planning_api.create_item(tmp_path, _make_item(id="G02"))
    planning_api.set_state(tmp_path, "G01", "completed")

    page = planning_api.list_items_page(tmp_path, state="all")
    ids = {i["id"] for i in page["items"]}
    assert ids == {"G01", "G02"}
    assert page["total"] == 2


def test_list_items_page_paginates_with_limit_and_offset(tmp_path):
    for i in range(1, 6):
        planning_api.create_item(tmp_path, _make_item(id=f"H0{i}"))

    page1 = planning_api.list_items_page(tmp_path, limit=2, offset=0)
    assert page1["returned"] == 2
    assert page1["total"] == 5
    assert page1["has_more"] is True

    page3 = planning_api.list_items_page(tmp_path, limit=2, offset=4)
    assert page3["returned"] == 1
    assert page3["has_more"] is False


def test_list_items_page_overflow_when_completed_item_matches_prefix(tmp_path):
    """When id_prefix matches only a completed item, overflow_items surface it."""
    planning_api.create_item(tmp_path, _make_item(id="MA31", plan="ml-tasks"))
    planning_api.set_state(tmp_path, "MA31", "completed")

    page = planning_api.list_items_page(tmp_path, id_prefix="MA31")
    assert page["items"] == []
    assert page["total"] == 0
    overflow = page["overflow_items"]
    assert len(overflow) == 1
    assert overflow[0]["id"] == "MA31"
    assert overflow[0]["state"] == "completed"
    assert "MA31" in page["note"]
    assert "completed" in page["note"]


def test_list_items_page_no_overflow_when_prefix_matches_active_item(tmp_path):
    """No overflow_items when the prefix match is within the active filter."""
    planning_api.create_item(tmp_path, _make_item(id="MA31", plan="ml-tasks"))

    page = planning_api.list_items_page(tmp_path, id_prefix="MA31")
    assert len(page["items"]) == 1
    assert "overflow_items" not in page


def test_list_items_page_no_overflow_when_prefix_has_no_matches_at_all(tmp_path):
    """No overflow_items when the prefix matches nothing anywhere."""
    planning_api.create_item(tmp_path, _make_item(id="MA31", plan="ml-tasks"))

    page = planning_api.list_items_page(tmp_path, id_prefix="Z99")
    assert page["items"] == []
    assert "overflow_items" not in page


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


def test_list_items_grouped_returns_groups(tmp_path):
    planning_api.create_item(tmp_path, {"plan": "test-plan", "title": "Item 1"})
    planning_api.create_item(tmp_path, {"plan": "test-plan", "title": "Item 2"})
    planning_api.create_item(tmp_path, {"plan": "other-plan", "title": "Other 1"})
    result = planning_api.list_items_grouped(tmp_path)
    groups = {g["plan"]: g for g in result}
    assert "plan-test-plan" in groups
    assert "plan-other-plan" in groups
    assert groups["plan-test-plan"]["item_count"] == 2
    assert groups["plan-test-plan"]["active_count"] == 2
    assert groups["plan-other-plan"]["item_count"] == 1


def test_list_items_grouped_with_state_filter(tmp_path):
    planning_api.create_item(tmp_path, {"plan": "test-plan", "title": "Active"})
    planning_api.create_item(tmp_path, {"plan": "test-plan", "title": "Done"})
    planning_api.set_state(tmp_path, "TE02", "completed")
    result = planning_api.list_items_grouped(tmp_path, state="completed")
    assert len(result) == 1
    assert result[0]["plan"] == "plan-test-plan"
    assert result[0]["completed_count"] == 1
    assert result[0]["active_count"] == 0


def test_next_item_id_sequential(tmp_path):
    planning_api.create_item(tmp_path, {"plan": "test-plan", "title": "First"})
    planning_api.create_item(tmp_path, {"plan": "test-plan", "title": "Second"})
    planning_api.create_item(tmp_path, {"plan": "test-plan", "title": "Third"})
    items = planning_api.list_items(tmp_path)
    ids = sorted([i["id"] for i in items])
    assert ids == ["TE01", "TE02", "TE03"]


def test_next_item_id_uses_established_plan_prefix(tmp_path):
    # 'code-cleanup' slices to 'CO', but the plan already uses 'CC' (e.g. an
    # initials-based prefix chosen when the plan was created). The generator
    # must follow the existing convention, not recompute a fresh guess.
    planning_api.create_item(tmp_path, {"id": "CC01", "plan": "code-cleanup", "title": "First"})
    result = planning_api.create_item(tmp_path, {"plan": "code-cleanup", "title": "Second"})
    assert result["id"] == "CC02"


def test_next_item_id_uses_established_prefix_from_completed_items(tmp_path):
    planning_api.create_item(tmp_path, {"id": "CC01", "plan": "code-cleanup", "title": "First"})
    planning_api.set_state(tmp_path, "CC01", "completed")
    result = planning_api.create_item(tmp_path, {"plan": "code-cleanup", "title": "Second"})
    assert result["id"] == "CC02"


def test_next_item_id_fallback_collision_raises(tmp_path):
    # Both slugs slice to the same 2-letter guess ('co'); the first plan claims
    # it via auto-generation, so the second plan must not silently alias it.
    planning_api.create_item(tmp_path, {"plan": "code-cleanup", "title": "First"})
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_item(tmp_path, {"plan": "config-leanness", "title": "First"})
    assert exc_info.value.code == "VAL-PLN-012"


# ---------------------------------------------------------------------------
# Config get/set (CC24) — planning-local-docs has no options-schema, so these
# register a synthetic implementation to exercise schema discovery/validation
# generically, same as any future implementation-backed planning backend would.
# ---------------------------------------------------------------------------

@pytest.fixture
def registered_test_implementation():
    from audiagentic.foundation.features.base import ImplementationDescriptor, OptionSchema
    from audiagentic.foundation.features.registry import clear as clear_features
    from audiagentic.foundation.features.registry import register

    clear_features()
    register(ImplementationDescriptor(
        parent="agent-planning",
        implementation_id="test-tracker",
        display_name="Test Tracker",
        options_schema={
            "api-token": OptionSchema(option_type="string", required=True, description="API token"),
            "timeout-seconds": OptionSchema(option_type="integer", default=30, description="Request timeout"),
        },
        raw={},
    ))
    yield "test-tracker"
    clear_features()


def test_planning_get_config_exposes_option_schema(tmp_path, registered_test_implementation):
    result = planning_api.planning_get_config(tmp_path, registered_test_implementation)
    assert result["implementation"] == "test-tracker"
    assert "api-token" in result["schema"]
    assert result["schema"]["api-token"]["required"] is True
    assert result["config"].get("timeout-seconds") == 30
    assert result["is_default"] is False


def test_planning_set_config_validates_unknown_option(tmp_path, registered_test_implementation):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.planning_set_config(tmp_path, registered_test_implementation, {"bogus": "x"})
    assert exc_info.value.code == "VAL-PLN-016"


def test_planning_set_config_validates_type(tmp_path, registered_test_implementation):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.planning_set_config(
            tmp_path, registered_test_implementation, {"timeout-seconds": "not-an-int"}
        )
    assert exc_info.value.code == "VAL-PLN-017"


def test_planning_set_config_persists(tmp_path, registered_test_implementation):
    result = planning_api.planning_set_config(
        tmp_path, registered_test_implementation, {"api-token": "secret"}
    )
    assert result["config"]["api-token"] == "secret"
    assert result["updated_keys"] == ["api-token"]

    fetched = planning_api.planning_get_config(tmp_path, registered_test_implementation)
    assert fetched["config"]["api-token"] == "secret"


def test_planning_set_config_unknown_implementation_raises(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.planning_set_config(tmp_path, "no-such-implementation", {"x": 1})
    assert exc_info.value.code == "VAL-PLN-015"


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

def test_create_review_writes_file(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    result = planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    assert result["id"] == "RV01"
    assert result["title"] == "Review 1"
    assert result["review-of"] == "ITM01"
    assert result["plan"] == "test-plan"
    target = tmp_path / result["path"]
    assert target.exists()


def test_create_review_records_reviewer_identity_alias(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(
        tmp_path,
        {"review-of": "ITM01", "title": "Review 1", "reviewer_id": "codex"},
    )
    review = planning_api.get_review(tmp_path, "RV01")
    listed = planning_api.list_reviews(tmp_path)

    assert review["reviewed-by"] == "codex"
    assert listed[0]["reviewed-by"] == "codex"


def test_create_review_event_includes_reviewer_identity(tmp_path, monkeypatch):
    published = []
    monkeypatch.setattr(planning_events, "publish_planning_event", lambda *args, **kwargs: published.append((args, kwargs)))
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    published.clear()

    planning_api.create_review(
        tmp_path,
        {"review-of": "ITM01", "title": "Review 1", "reviewer_id": "codex"},
    )

    event_type, payload = published[0][0]
    assert event_type == planning_events.PLANNING_REVIEW_CREATED
    assert payload["id"] == "RV01"
    assert payload["reviewed-by"] == "codex"
    assert published[0][1]["subject_id"] == "RV01"


def test_update_review_accepts_reviewer_identity_alias(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.update_review(tmp_path, "RV01", {"reviewed_by": "claude"})

    assert planning_api.get_review(tmp_path, "RV01")["reviewed-by"] == "claude"


def test_update_review_event_includes_reviewer_identity(tmp_path, monkeypatch):
    published = []
    monkeypatch.setattr(planning_events, "publish_planning_event", lambda *args, **kwargs: published.append((args, kwargs)))
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1", "reviewer_id": "codex"})
    published.clear()

    planning_api.update_review(tmp_path, "RV01", {"reviewed_by": "claude"})

    event_type, payload = published[0][0]
    assert event_type == planning_events.PLANNING_REVIEW_UPDATED
    assert payload["reviewed-by"] == "claude"
    assert payload["updated_keys"] == ["reviewed_by"]


# ---------------------------------------------------------------------------
# Item/review tool cross-contamination guards
#
# _find_item locates files by <id>.md alone, regardless of whether the id
# belongs to a plan item or a review — item-scoped and review-scoped
# functions previously had no check that the file they found was actually
# their kind. update_item in particular would silently rewrite a review
# using the item's section template (description/steps/files/validation/
# effort_risk/standards/notes), discarding the review's findings/conclusion
# and dropping any updates keyed by findings/conclusion (neither key matches
# an item section) with no error at all — real, silent data loss.
# ---------------------------------------------------------------------------

def _make_review(tmp_path, item_id="ITM01", review_id="RV01", **overrides):
    planning_api.create_item(tmp_path, {"id": item_id, "plan": "test-plan", "title": "Item 1"})
    review = {"id": review_id, "review-of": item_id, "title": "A review", "findings": "the original findings", **overrides}
    return planning_api.create_review(tmp_path, review)


def test_update_item_rejects_review_id(tmp_path):
    _make_review(tmp_path)
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.update_item(tmp_path, "RV01", {"notes": "clobbered"})
    assert exc_info.value.code == "VAL-PLN-020"
    # the review's original content must be completely untouched
    review = planning_api.get_review(tmp_path, "RV01")
    assert review["findings"] == "the original findings"


def test_get_item_rejects_review_id(tmp_path):
    _make_review(tmp_path)
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.get_item(tmp_path, "RV01")
    assert exc_info.value.code == "VAL-PLN-018"


def test_delete_item_rejects_review_id(tmp_path):
    _make_review(tmp_path)
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.delete_item(tmp_path, "RV01")
    assert exc_info.value.code == "VAL-PLN-021"
    # must still exist — delete_item must not have removed it
    assert planning_api.get_review(tmp_path, "RV01")["id"] == "RV01"


def test_set_state_rejects_review_id(tmp_path):
    _make_review(tmp_path)
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.set_state(tmp_path, "RV01", "completed")
    assert exc_info.value.code == "VAL-PLN-019"


def test_update_review_rejects_item_id(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.update_review(tmp_path, "ITM01", {"conclusion": "clobbered"})
    assert exc_info.value.code == "VAL-PLN-023"
    # the item's original content must be completely untouched
    item = planning_api.get_item(tmp_path, "ITM01")
    assert item["title"] == "Item 1"


def test_get_review_rejects_item_id(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.get_review(tmp_path, "ITM01")
    assert exc_info.value.code == "VAL-PLN-022"


def test_delete_review_rejects_item_id(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.delete_review(tmp_path, "ITM01")
    assert exc_info.value.code == "VAL-PLN-024"
    assert planning_api.get_item(tmp_path, "ITM01")["id"] == "ITM01"


def test_set_review_state_rejects_item_id(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.set_review_state(tmp_path, "ITM01", "closed")
    assert exc_info.value.code == "VAL-PLN-013"


def test_create_review_auto_generates_id(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "First review"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Second review"})
    reviews = planning_api.list_reviews(tmp_path)
    ids = sorted([r["id"] for r in reviews])
    assert ids == ["RV01", "RV02"]


def test_create_review_requires_parent(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_review(tmp_path, {"title": "Orphan review"})
    assert exc_info.value.code == "VAL-PLN-008"


def test_create_review_parent_not_found(tmp_path):
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_review(tmp_path, {"review-of": "GHOST01", "title": "Review"})
    assert exc_info.value.code == "VAL-PLN-010"


def test_create_review_requires_title(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.create_review(tmp_path, {"review-of": "ITM01"})
    assert exc_info.value.code == "VAL-PLN-009"


def test_get_review_returns_sections(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {
        "review-of": "ITM01",
        "title": "Review 1",
        "notes": "Some notes",
        "findings": "Key findings here",
        "conclusion": "Approved",
    })
    review = planning_api.get_review(tmp_path, "RV01")
    assert review["id"] == "RV01"
    assert review["review-of"] == "ITM01"
    assert review["notes"] == "Some notes"
    assert review["findings"] == "Key findings here"
    assert review["conclusion"] == "Approved"
    assert review["state"] == "created"


def test_list_reviews_filters_by_state(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Active review"})
    planning_api.set_review_state(tmp_path, "RV01", "closed")
    active = planning_api.list_reviews(tmp_path, state="created")
    assert len(active) == 0
    closed = planning_api.list_reviews(tmp_path, state="closed")
    assert len(closed) == 1
    assert closed[0]["id"] == "RV01"
    assert closed[0]["state"] == "closed"


def test_list_reviews_filters_by_review_of(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_item(tmp_path, {"id": "ITM02", "plan": "test-plan", "title": "Item 2"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review for Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM02", "title": "Review for Item 2"})
    reviews = planning_api.list_reviews(tmp_path, review_of="ITM01")
    assert len(reviews) == 1
    assert reviews[0]["review-of"] == "ITM01"


def test_list_reviews_id_prefix_filter(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.create_review(tmp_path, {"id": "OTHER01", "review-of": "ITM01", "title": "Odd id"})

    reviews = planning_api.list_reviews(tmp_path, id_prefix="rv")
    ids = {r["id"] for r in reviews}
    assert ids == {"RV01"}


def test_list_reviews_page_defaults_to_open_state(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Open review"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Closed review"})
    planning_api.set_review_state(tmp_path, "RV02", "closed")

    page = planning_api.list_reviews_page(tmp_path)
    ids = {r["id"] for r in page["items"]}
    assert ids == {"RV01"}
    assert page["total"] == 1


def test_list_reviews_page_state_all_includes_closed(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Open review"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Closed review"})
    planning_api.set_review_state(tmp_path, "RV02", "closed")

    page = planning_api.list_reviews_page(tmp_path, state="all")
    ids = {r["id"] for r in page["items"]}
    assert ids == {"RV01", "RV02"}
    assert page["total"] == 2


def test_set_review_state_moves_to_completed(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    result = planning_api.set_review_state(tmp_path, "RV01", "closed")
    assert result["state"] == "closed"
    review = planning_api.get_review(tmp_path, "RV01")
    assert review["state"] == "closed"


def test_update_review_changes_sections(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.update_review(tmp_path, "RV01", {
        "notes": "Updated notes",
        "findings": "Updated findings",
    })
    review = planning_api.get_review(tmp_path, "RV01")
    assert review["notes"] == "Updated notes"
    assert review["findings"] == "Updated findings"


def test_delete_review_removes_file(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.delete_review(tmp_path, "RV01")
    with pytest.raises(AudiaGenticError) as exc_info:
        planning_api.get_review(tmp_path, "RV01")
    assert exc_info.value.code == "VAL-PLN-001"


def test_review_id_sequential_across_states(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "First"})
    planning_api.set_review_state(tmp_path, "RV01", "closed")
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Second"})
    reviews = planning_api.list_reviews(tmp_path)
    ids = sorted([r["id"] for r in reviews])
    assert ids == ["RV01", "RV02"]


def test_review_id_is_globally_unique_across_plans(tmp_path):
    # Review IDs are checked for uniqueness globally, so numbering must be global:
    # a second plan's first review must not restart at RV01 and collide.
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "plan-a", "title": "Item A"})
    planning_api.create_item(tmp_path, {"id": "ITM02", "plan": "plan-b", "title": "Item B"})
    first = planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "For A"})
    second = planning_api.create_review(tmp_path, {"review-of": "ITM02", "title": "For B"})
    assert first["id"] == "RV01"
    assert second["id"] == "RV02"


# ---------------------------------------------------------------------------
# Empty plan directory cleanup
# ---------------------------------------------------------------------------

def test_set_state_to_completed_cleans_up_empty_active_plan_dir(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.set_state(tmp_path, "TST01", "completed")
    active_plan_dir = _active_dir(tmp_path) / "test-plan"
    assert not active_plan_dir.exists()


def test_set_state_to_completed_preserves_plan_dir_with_other_items(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="TST01"))
    planning_api.create_item(tmp_path, _make_item(id="TST02"))
    planning_api.set_state(tmp_path, "TST01", "completed")
    active_plan_dir = _active_dir(tmp_path) / "test-plan"
    assert active_plan_dir.exists()
    assert (active_plan_dir / "TST02.md").exists()


def test_set_state_to_completed_preserves_plan_dir_with_reviews(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.set_state(tmp_path, "ITM01", "completed")
    active_plan_dir = _active_dir(tmp_path) / "test-plan"
    assert active_plan_dir.exists()
    assert (active_plan_dir / "reviews" / "ITM01" / "RV01.md").exists()


def test_set_state_from_completed_cleans_up_empty_completed_plan_dir(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.set_state(tmp_path, "TST01", "completed")
    planning_api.set_state(tmp_path, "TST01", "pending")
    completed_plan_dir = _completed_dir(tmp_path) / "test-plan"
    assert not completed_plan_dir.exists()


def test_delete_item_cleans_up_empty_active_plan_dir(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.delete_item(tmp_path, "TST01")
    active_plan_dir = _active_dir(tmp_path) / "test-plan"
    assert not active_plan_dir.exists()


def test_delete_item_cleans_up_empty_completed_plan_dir(tmp_path):
    planning_api.create_item(tmp_path, _make_item())
    planning_api.set_state(tmp_path, "TST01", "completed")
    planning_api.delete_item(tmp_path, "TST01")
    completed_plan_dir = _completed_dir(tmp_path) / "test-plan"
    assert not completed_plan_dir.exists()


def test_delete_item_preserves_plan_dir_with_other_items(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="TST01"))
    planning_api.create_item(tmp_path, _make_item(id="TST02"))
    planning_api.delete_item(tmp_path, "TST01")
    active_plan_dir = _active_dir(tmp_path) / "test-plan"
    assert active_plan_dir.exists()
    assert (active_plan_dir / "TST02.md").exists()


def test_delete_review_preserves_plan_dir_with_parent_item(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.delete_review(tmp_path, "RV01")
    active_plan_dir = _active_dir(tmp_path) / "test-plan"
    assert active_plan_dir.exists()
    assert not (active_plan_dir / "reviews").exists()


def test_set_review_state_moves_review_between_states(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.set_review_state(tmp_path, "RV01", "closed")
    completed_plan_dir = _completed_dir(tmp_path) / "test-plan" / "reviews" / "ITM01"
    assert (completed_plan_dir / "RV01.md").exists()
    assert not (_active_dir(tmp_path) / "test-plan" / "reviews").exists()


def test_set_review_state_to_closed_cleans_up_empty_active_plan_dir(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.set_state(tmp_path, "ITM01", "completed")
    planning_api.set_review_state(tmp_path, "RV01", "closed")

    assert not (_active_dir(tmp_path) / "test-plan").exists()
    assert (_completed_dir(tmp_path) / "test-plan" / "ITM01.md").exists()
    assert (_completed_dir(tmp_path) / "test-plan" / "reviews" / "ITM01" / "RV01.md").exists()


def test_set_review_state_moves_review_back_to_active(tmp_path):
    planning_api.create_item(tmp_path, {"id": "ITM01", "plan": "test-plan", "title": "Item 1"})
    planning_api.create_review(tmp_path, {"review-of": "ITM01", "title": "Review 1"})
    planning_api.set_review_state(tmp_path, "RV01", "closed")
    planning_api.set_review_state(tmp_path, "RV01", "created")
    active_plan_dir = _active_dir(tmp_path) / "test-plan" / "reviews" / "ITM01"
    assert (active_plan_dir / "RV01.md").exists()


def test_multiple_plans_cleanup_only_empty_one(tmp_path):
    planning_api.create_item(tmp_path, _make_item(id="A01", plan="alpha"))
    planning_api.create_item(tmp_path, _make_item(id="B01", plan="beta"))
    planning_api.set_state(tmp_path, "A01", "completed")
    planning_api.set_state(tmp_path, "B01", "completed")
    planning_api.set_state(tmp_path, "A01", "pending")
    active_alpha = _active_dir(tmp_path) / "alpha"
    active_beta = _active_dir(tmp_path) / "beta"
    completed_alpha = _completed_dir(tmp_path) / "alpha"
    completed_beta = _completed_dir(tmp_path) / "beta"
    assert active_alpha.exists()
    assert not active_beta.exists()
    assert not completed_alpha.exists()
    assert completed_beta.exists()
