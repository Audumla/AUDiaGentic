"""Unit tests for planning_mcp — verify MCP tools delegate to planning_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.planning import planning_mcp

_ROOT = Path("/fake/root")


def _patch_root():
    return patch(
        "audiagentic.components.planning.planning_mcp.project_root_from_env",
        return_value=_ROOT,
    )


def test_plan_create_item_delegates_to_api():
    item = {"id": "X01", "plan": "test", "title": "T"}
    with _patch_root(), patch(
        "audiagentic.components.planning.planning_api.create_item",
        return_value={"ok": True},
    ) as mock:
        result = planning_mcp.plan_create_item(item)
    assert result == {"ok": True}
    mock.assert_called_once_with(_ROOT, item)


def test_plan_list_items_delegates_to_api():
    page = {"items": [], "total": 0, "returned": 0, "offset": 0, "limit": 50, "has_more": False}
    with _patch_root(), patch(
        "audiagentic.components.planning.planning_api.list_items_page",
        return_value=page,
    ) as mock:
        result = planning_mcp.plan_list_items(state="active", plan="my-plan")
    assert result == page
    mock.assert_called_once_with(_ROOT, "active", "my-plan", None, 50, 0)


def test_plan_list_items_defaults_none_filters():
    page = {"items": [], "total": 0, "returned": 0, "offset": 0, "limit": 50, "has_more": False}
    with _patch_root(), patch(
        "audiagentic.components.planning.planning_api.list_items_page",
        return_value=page,
    ) as mock:
        planning_mcp.plan_list_items()
    mock.assert_called_once_with(_ROOT, None, None, None, 50, 0)


def test_plan_get_item_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.planning.planning_api.get_item",
        return_value={"id": "X01"},
    ) as mock:
        result = planning_mcp.plan_get_item("X01")
    assert result == {"id": "X01"}
    mock.assert_called_once_with(_ROOT, "X01")


def test_plan_set_state_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.planning.planning_api.set_state",
        return_value={"ok": True, "state": "completed"},
    ) as mock:
        result = planning_mcp.plan_set_state("X01", "completed")
    assert result["state"] == "completed"
    mock.assert_called_once_with(_ROOT, "X01", "completed")


def test_plan_update_item_delegates_to_api():
    updates = {"priority": "P0"}
    with _patch_root(), patch(
        "audiagentic.components.planning.planning_api.update_item",
        return_value={"ok": True},
    ) as mock:
        result = planning_mcp.plan_update_item("X01", updates)
    assert result == {"ok": True}
    mock.assert_called_once_with(_ROOT, "X01", updates)


def test_plan_delete_item_delegates_to_api():
    with _patch_root(), patch(
        "audiagentic.components.planning.planning_api.delete_item",
        return_value={"ok": True},
    ) as mock:
        result = planning_mcp.plan_delete_item("X01")
    assert result == {"ok": True}
    mock.assert_called_once_with(_ROOT, "X01")
