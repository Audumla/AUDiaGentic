from __future__ import annotations

from pathlib import Path

from audiagentic.components.ledger.fragments import record_change_event
from audiagentic.components.ledger.ledger_events import register
from audiagentic.components.release.events import RELEASE_LEDGER_ARCHIVE_REQUESTED
from audiagentic.foundation.event import DeliveryMode, get_bus


def _event(event_id: str) -> dict:
    return {
        "contract-version": "v1",
        "event-id": event_id,
        "timestamp-utc": "2026-05-30T00:00:00Z",
        "project-id": "AUDiaGentic",
        "source": {
            "kind": "interactive-prompt",
            "provider-id": "codex",
            "surface": "terminal",
            "session-id": None,
            "job-id": None,
            "packet-id": None,
            "prompt-tag": "implement",
            "target-kind": "adhoc",
            "target-ref": "test",
            "review-id": None,
        },
        "change-class": "refactor",
        "files": ["src/example.py"],
        "diff-stats": {"files-changed": 1, "insertions": 1, "deletions": 0},
        "technical-summary": "test",
        "user-summary-candidate": "test",
        "status": "unreleased",
    }


def test_ledger_handles_release_archive_event(tmp_path: Path) -> None:
    register()
    record_change_event(tmp_path, _event("chg_release_event"))
    result: dict = {}

    get_bus().publish(
        RELEASE_LEDGER_ARCHIVE_REQUESTED,
        {
            "project_root": tmp_path,
            "release_id": "rel_event",
            "result": result,
        },
        mode=DeliveryMode.SYNC,
    )

    assert result["release-id"] == "rel_event"
    assert result["archived-events"] == 1
    assert result["released-event-ids"] == ["chg_release_event"]
