from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.ledger.current_events import event_file_name
from audiagentic.components.ledger.recorder import record_change_event
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.package import REPO_ROOT

FIXTURES = REPO_ROOT / "docs" / "examples" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_record_creates_one_event_file(tmp_path: Path) -> None:
    event = _load("change-event.valid.json")
    result = record_change_event(tmp_path, event)
    assert result["status"] == "created"
    path = tmp_path / "docs" / "releases" / "events" / event_file_name(event["event-id"])
    assert path.is_file() and result["event-path"] == str(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == event


def test_record_fragment_idempotent(tmp_path: Path) -> None:
    event = _load("change-event.valid.json")
    record_change_event(tmp_path, event)
    result = record_change_event(tmp_path, event)
    assert result["status"] == "exists"


def test_record_fragment_invalid_event(tmp_path: Path) -> None:
    event = _load("change-event.invalid.json")
    try:
        record_change_event(tmp_path, event)
    except AudiaGenticError as exc:
        assert exc.kind == "release"
        assert not (tmp_path / "docs" / "releases" / "events").exists()
    else:
        raise AssertionError("expected validation error")
