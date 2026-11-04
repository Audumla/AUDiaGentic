"""Plan-item links to ledger events are derived from each event's plan-item-ids, never written to a plan file."""

from __future__ import annotations

import json
import subprocess

import pytest

from audiagentic.components.ledger import ledger_api
from audiagentic.components.ledger.recorder import record_change_event
from audiagentic.components.planning import planning_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _event(event_id: str, plan_items: list[str], **extra) -> dict:
    return {"event-id": event_id, "timestamp-utc": "2026-11-01T00:00:00Z", "change-class": "feature",
            "files": ["src/a.py"], "technical-summary": "t", "user-summary-candidate": f"summary {event_id}",
            "status": "unreleased", "plan-item-ids": plan_items, **extra}


def _create(root, item_id="TST01"):
    planning_api.create_item(root, {"id": item_id, "plan": "test-plan", "title": "Test", "created-by": "test"})
    return root / "docs" / "planning" / "active" / "test-plan" / f"{item_id}.md"


def test_recording_an_event_never_edits_the_plan_item_but_the_ledger_lists_it(tmp_path):
    path = _create(tmp_path)
    before = path.read_text(encoding="utf-8")

    record_change_event(tmp_path, _event("chg_001", ["TST01"]))
    record_change_event(tmp_path, _event("chg_002", ["TST01", "OTHER"]))
    record_change_event(tmp_path, _event("chg_003", ["OTHER"]))

    assert path.read_text(encoding="utf-8") == before
    linked = ledger_api.plan_item_events(tmp_path, "TST01")
    assert [event["event-id"] for event in linked] == ["chg_001", "chg_002"]
    assert linked[0]["status"] == "unreleased" and linked[0]["user-summary-candidate"] == "summary chg_001"


def test_released_events_are_still_linked_and_marked_released(tmp_path):
    event = _event("chg_old", ["TST01"])
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    historical.parent.mkdir(parents=True)
    historical.write_text(json.dumps({**event, "status": "released", "release-id": "rel_1"}) + "\n", encoding="utf-8")
    record_change_event(tmp_path, _event("chg_new", ["TST01"], **{"timestamp-utc": "2026-11-02T00:00:00Z"}))

    linked = ledger_api.plan_item_events(tmp_path, "TST01")

    assert [(e["event-id"], e["status"], e["release-id"]) for e in linked] == [
        ("chg_old", "released", "rel_1"), ("chg_new", "unreleased", None)]


def test_a_current_event_conflicting_with_a_released_id_fails_closed_not_mislabelled(tmp_path):
    released = _event("chg_1", ["CC01"])
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    historical.parent.mkdir(parents=True)
    historical.write_text(json.dumps({**released, "status": "released", "release-id": "rel_1"}) + "\n", encoding="utf-8")
    events_dir = tmp_path / "docs" / "releases" / "events"
    events_dir.mkdir()
    from audiagentic.components.ledger.current_events import event_file_name, event_text

    conflicting = _event("chg_1", ["CC02"])
    (events_dir / event_file_name("chg_1")).write_text(event_text(conflicting), encoding="utf-8")

    with pytest.raises(AudiaGenticError, match="conflicting content"):
        ledger_api.plan_item_events(tmp_path, "CC02")


def test_legacy_ledger_events_text_in_a_plan_file_is_kept_but_superseded(tmp_path):
    path = _create(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n## Ledger-events\n\n- chg_legacy\n", encoding="utf-8")
    record_change_event(tmp_path, _event("chg_001", ["TST01"]))

    assert "- chg_legacy" in path.read_text(encoding="utf-8")  # history is not rewritten
    assert [e["event-id"] for e in ledger_api.plan_item_events(tmp_path, "TST01")] == ["chg_001"]


def test_two_branches_recording_events_for_one_plan_item_do_not_conflict(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    _create(tmp_path)
    git("add", "-A")
    git("commit", "-q", "-m", "item")
    for branch, event_id in (("one", "chg_one"), ("two", "chg_two")):
        git("checkout", "-q", "-B", branch, "main")
        record_change_event(tmp_path, _event(event_id, ["TST01"]))
        git("add", "-A")
        git("commit", "-q", "-m", branch)
    git("checkout", "-q", "-B", "merged", "one")
    git("merge", "-q", "--no-edit", "two")  # raises on a conflict

    assert [e["event-id"] for e in ledger_api.plan_item_events(tmp_path, "TST01")] == ["chg_one", "chg_two"]
