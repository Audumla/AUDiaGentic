"""Tests for planning event subscribers."""

from __future__ import annotations

from audiagentic.components.planning import planning_api
from audiagentic.components.planning.events import _on_ledger_event_recorded


def test_replayed_ledger_event_is_linked_once(tmp_path):
    planning_api.create_item(
        tmp_path,
        {"id": "TST01", "plan": "test-plan", "title": "Test", "created-by": "test"},
    )
    payload = {
        "project_root": tmp_path,
        "event-id": "chg_001",
        "plan-item-ids": ["TST01"],
    }

    _on_ledger_event_recorded("ledger.event.recorded", payload, {})
    _on_ledger_event_recorded("ledger.event.recorded", payload, {})

    path = tmp_path / "docs" / "planning" / "active" / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    assert text.count("## Ledger-events") == 1
    assert text.count("- chg_001") == 1
    item = planning_api.get_item(tmp_path, "TST01", include_history=True)
    assert sum(entry["description"] == "Updated: section:ledger-events" for entry in item["change_log"]) == 1
