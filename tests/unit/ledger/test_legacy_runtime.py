"""The one-time migration of events an older layout left in the runtime directory."""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.ledger import ledger_api
from audiagentic.components.ledger.current_events import event_path, pending_events
from audiagentic.components.ledger.legacy_runtime import migrate_legacy_runtime


def _event(event_id: str, **extra) -> dict:
    return {"event-id": event_id, "timestamp-utc": "2026-11-01T00:00:00Z", "change-class": "feature",
            "files": ["src/a.py"], "technical-summary": "t", "user-summary-candidate": "u",
            "status": "unreleased", **extra}


def _runtime(root: Path) -> Path:
    return root / ".audiagentic" / "runtime" / "ledger"


def test_retained_fragments_and_outbox_events_become_event_files_then_are_removed(tmp_path: Path) -> None:
    (_runtime(tmp_path) / "fragments").mkdir(parents=True)
    (_runtime(tmp_path) / "event-outbox").mkdir(parents=True)
    (_runtime(tmp_path) / "fragments" / "chg_frag.json").write_text(json.dumps(_event("chg_frag")))
    (_runtime(tmp_path) / "event-outbox" / "chg_box.json").write_text(
        json.dumps({"event-id": "chg_box", "plan-item-ids": ["TST01"], "event": _event("chg_box")}))

    result = migrate_legacy_runtime(tmp_path)

    assert result == {"migrated": 2, "already-released": 0, "left-in-place": []}
    assert event_path(tmp_path, "chg_frag").is_file() and event_path(tmp_path, "chg_box").is_file()
    assert not (_runtime(tmp_path) / "fragments").exists() and not (_runtime(tmp_path) / "event-outbox").exists()
    assert migrate_legacy_runtime(tmp_path)["migrated"] == 0  # a second run is a no-op


def test_an_already_released_event_is_dropped_not_resurrected_and_a_conflict_is_kept(tmp_path: Path) -> None:
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    historical.parent.mkdir(parents=True)
    released = _event("chg_rel")
    historical.write_text(json.dumps({**released, "status": "released", "release-id": "r1"}) + "\n")
    (_runtime(tmp_path) / "fragments").mkdir(parents=True)
    (_runtime(tmp_path) / "fragments" / "chg_rel.json").write_text(json.dumps(released))
    (_runtime(tmp_path) / "fragments" / "chg_conflict.json").write_text(json.dumps(_event("chg_conflict")))
    historical.write_text(historical.read_text() + json.dumps(
        {**_event("chg_conflict", **{"technical-summary": "other"}), "status": "released", "release-id": "r1"}) + "\n")

    result = migrate_legacy_runtime(tmp_path)

    assert result["already-released"] == 1 and result["left-in-place"] == ["fragments/chg_conflict.json"]
    assert not event_path(tmp_path, "chg_rel").exists()
    assert (_runtime(tmp_path) / "fragments" / "chg_conflict.json").exists()  # never discarded


def test_unparseable_records_are_left_in_place_and_sync_and_release_migrate_first(tmp_path: Path) -> None:
    (_runtime(tmp_path) / "fragments").mkdir(parents=True)
    (_runtime(tmp_path) / "fragments" / "junk.json").write_text("{not json")
    (_runtime(tmp_path) / "fragments" / "chg_ok.json").write_text(json.dumps(_event("chg_ok")))

    assert ledger_api.sync(tmp_path)["migrated-legacy-events"] == 1
    assert (_runtime(tmp_path) / "fragments" / "junk.json").exists()
    assert [e["event-id"] for e in pending_events(tmp_path)] == ["chg_ok"]

    (_runtime(tmp_path) / "fragments" / "chg_late.json").write_text(json.dumps(_event("chg_late")))
    assert ledger_api.archive_for_release(tmp_path, "rel_1")["released-event-ids"] == ["chg_late", "chg_ok"]
