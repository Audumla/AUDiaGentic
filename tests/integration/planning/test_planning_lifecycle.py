"""Integration tests for the full planning item lifecycle.

Uses tmp_path for filesystem isolation — no Docker, no network.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.planning import planning_api, planning_paths


def _active(root: Path) -> Path:
    return planning_paths.plans_active_dir(root)


def _completed(root: Path) -> Path:
    return planning_paths.plans_completed_dir(root)


def test_full_lifecycle_create_update_complete(tmp_path):
    """Create → update → complete — item ends up in completed/ with correct state."""
    planning_api.create_item(tmp_path, {
        "id": "LF01",
        "plan": "lifecycle-test",
        "title": "Lifecycle item",
        "priority": "P1",
        "description": "Initial description.",
    })

    planning_api.update_item(tmp_path, "LF01", {
        "description": "Updated description.",
        "steps": "Step 1. Step 2.",
    })

    planning_api.set_state(tmp_path, "LF01", "completed")

    item = planning_api.get_item(tmp_path, "LF01")
    assert item["state"] == "completed"
    assert item["description"] == "Updated description."
    assert item["steps"] == "Step 1. Step 2."
    assert not (_active(tmp_path) / "lifecycle-test" / "LF01.md").exists()
    assert (_completed(tmp_path) / "lifecycle-test" / "LF01.md").exists()


def test_multiple_plans_isolated(tmp_path):
    """Items in different plans are independent."""
    planning_api.create_item(tmp_path, {"id": "AP01", "plan": "alpha", "title": "Alpha"})
    planning_api.create_item(tmp_path, {"id": "BE01", "plan": "beta", "title": "Beta"})

    alpha = planning_api.list_items(tmp_path, plan="alpha")
    beta = planning_api.list_items(tmp_path, plan="beta")

    assert [i["id"] for i in alpha] == ["AP01"]
    assert [i["id"] for i in beta] == ["BE01"]


def test_list_reflects_state_after_transition(tmp_path):
    """list_items with state filters is consistent after set_state."""
    for i in range(1, 4):
        planning_api.create_item(tmp_path, {"id": f"LS{i:02d}", "plan": "list-test", "title": f"Item {i}"})

    planning_api.set_state(tmp_path, "LS01", "completed")
    planning_api.set_state(tmp_path, "LS02", "completed")

    active = planning_api.list_items(tmp_path, state="active")
    done = planning_api.list_items(tmp_path, state="completed")

    assert {i["id"] for i in active} == {"LS03"}
    assert {i["id"] for i in done} == {"LS01", "LS02"}


def test_delete_removes_from_list(tmp_path):
    """Deleted items no longer appear in list_items."""
    planning_api.create_item(tmp_path, {"id": "DL01", "plan": "del-test", "title": "Delete me"})
    planning_api.create_item(tmp_path, {"id": "DL02", "plan": "del-test", "title": "Keep me"})
    planning_api.delete_item(tmp_path, "DL01")

    items = planning_api.list_items(tmp_path)
    assert all(i["id"] != "DL01" for i in items)
    assert any(i["id"] == "DL02" for i in items)


def test_completed_item_can_be_reopened(tmp_path):
    """set_state pending on a completed item moves it back to active/."""
    planning_api.create_item(tmp_path, {"id": "RO01", "plan": "reopen", "title": "Reopen me"})
    planning_api.set_state(tmp_path, "RO01", "completed")
    planning_api.set_state(tmp_path, "RO01", "pending")

    item = planning_api.get_item(tmp_path, "RO01")
    assert item["state"] == "pending"
    assert (_active(tmp_path) / "reopen" / "RO01.md").exists()
    assert not (_completed(tmp_path) / "reopen" / "RO01.md").exists()


def test_round_trip_all_sections(tmp_path):
    """All body sections survive a create → get round-trip."""
    sections = {
        "description": "What to do.",
        "steps": "1. Do it.",
        "files": "src/foo.py",
        "validation": "Tests pass.",
        "effort_risk": "Low risk.",
        "notes": "See ticket #42.",
    }
    planning_api.create_item(tmp_path, {
        "id": "RT01",
        "plan": "roundtrip",
        "title": "Round-trip test",
        **sections,
    })

    item = planning_api.get_item(tmp_path, "RT01")
    for key, expected in sections.items():
        assert item[key] == expected, f"section {key!r} mismatch"


def test_get_after_update_reflects_changes(tmp_path):
    """get_item after update_item returns the new values."""
    planning_api.create_item(tmp_path, {"id": "UP01", "plan": "update-test", "title": "Original"})
    planning_api.update_item(tmp_path, "UP01", {
        "title": "Revised",
        "priority": "P0",
        "notes": "Important change.",
    })

    item = planning_api.get_item(tmp_path, "UP01")
    assert item["title"] == "Revised"
    assert item["priority"] == "P0"
    assert item["notes"] == "Important change."


def test_legacy_not_done_alias_resolves_to_pending(tmp_path):
    """not_done is accepted and stores canonical 'pending' in frontmatter."""
    planning_api.create_item(tmp_path, {"id": "ND01", "plan": "legacy", "title": "Legacy"})
    planning_api.set_state(tmp_path, "ND01", "completed")
    result = planning_api.set_state(tmp_path, "ND01", "not_done")

    assert result["state"] == "pending"
    item = planning_api.get_item(tmp_path, "ND01")
    assert item["state"] == "pending"
