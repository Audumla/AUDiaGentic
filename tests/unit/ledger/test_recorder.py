from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.ledger import recorder as fragments
from audiagentic.components.ledger.current_events import event_file_name


def _event() -> dict:
    return {
        "event-id": "chg_existing",
        "timestamp-utc": "2026-08-14T00:00:00Z",
        "change-class": "code-fix",
        "files": ["src/example.py"],
        "technical-summary": "summary",
        "user-summary-candidate": "summary",
        "status": "unreleased",
        "plan-item-ids": ["TST01"],
    }


def test_existing_event_republishes_projection(monkeypatch, tmp_path: Path):
    event = _event()
    path = tmp_path / "docs" / "releases" / "events" / event_file_name("chg_existing")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(event), encoding="utf-8")
    published: list[tuple] = []
    monkeypatch.setattr(
        fragments,
        "publish_ledger_event_recorded",
        lambda *args, **kwargs: published.append((args, kwargs)),
    )

    result = fragments.record_change_event(tmp_path, dict(event))

    assert result["status"] == "exists"
    assert len(published) == 1
    args, kwargs = published[0]
    assert args[:3] == ("chg_existing", ["TST01"], tmp_path)
    assert kwargs["timestamp_utc"] == event["timestamp-utc"]
