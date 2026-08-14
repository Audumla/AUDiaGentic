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


def test_ledger_link_migrates_duplicate_legacy_sections_without_losing_history(tmp_path):
    planning_api.create_item(
        tmp_path,
        {"id": "TST01", "plan": "test-plan", "title": "Test", "created-by": "test"},
    )
    path = tmp_path / "docs" / "planning" / "active" / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "\n## Notes\n\n",
        "\n## Ledger-events\n\n- chg_old_1\n\n## Notes\n\n",
    )
    text = text.rstrip() + "\n\n## Ledger-events\n\n- chg_old_2\n"
    path.write_text(text, encoding="utf-8")

    _on_ledger_event_recorded(
        "ledger.event.recorded",
        {"project_root": tmp_path, "event-id": "chg_new", "plan-item-ids": ["TST01"]},
        {},
    )

    result = path.read_text(encoding="utf-8")
    assert result.count("## Ledger-events") == 1
    assert all(f"- {event}" in result for event in ("chg_old_1", "chg_old_2", "chg_new"))


def test_ledger_link_deduplicates_existing_event_ids_and_bullet_styles(tmp_path):
    planning_api.create_item(
        tmp_path,
        {"id": "TST01", "plan": "test-plan", "title": "Test", "created-by": "test"},
    )
    path = tmp_path / "docs" / "planning" / "active" / "test-plan" / "TST01.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("\n## Notes\n\n", "\n## Ledger-events\n\n- chg_dup\n\n## Notes\n\n")
    text = text.rstrip() + "\n\n## Ledger events\n\n* chg_dup\n- chg_other\n"
    path.write_text(text, encoding="utf-8")

    _on_ledger_event_recorded(
        "ledger.event.recorded",
        {"project_root": tmp_path, "event-id": "chg_dup", "plan-item-ids": ["TST01"]},
        {},
    )

    result = path.read_text(encoding="utf-8")
    assert result.count("## Ledger-events") == 1
    assert result.count("- chg_dup") == 1
    assert result.count("- chg_other") == 1


def test_concurrent_ledger_events_are_append_only(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    planning_api.create_item(
        tmp_path,
        {"id": "TST01", "plan": "test-plan", "title": "Test", "created-by": "test"},
    )

    def deliver(event_id: str):
        _on_ledger_event_recorded(
            "ledger.event.recorded",
            {"project_root": tmp_path, "event-id": event_id, "plan-item-ids": ["TST01"]},
            {},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(deliver, ["chg_a", "chg_b"]))

    path = tmp_path / "docs" / "planning" / "active" / "test-plan" / "TST01.md"
    result = path.read_text(encoding="utf-8")
    assert result.count("## Ledger-events") == 1
    assert result.count("- chg_a") == 1
    assert result.count("- chg_b") == 1
