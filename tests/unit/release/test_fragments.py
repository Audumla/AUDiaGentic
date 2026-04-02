from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.runtime.release.fragments import record_change_event

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_record_fragment_creates_file(tmp_path: Path) -> None:
    event = _load("change-event.valid.json")
    result = record_change_event(tmp_path, event)
    assert result["status"] == "created"
    fragment = tmp_path / ".audiagentic" / "runtime" / "ledger" / "fragments" / f"{event['event-id']}.json"
    assert fragment.is_file()
    payload = json.loads(fragment.read_text(encoding="utf-8"))
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
        assert exc.kind == "validation"
        fragment_dir = tmp_path / ".audiagentic" / "runtime" / "ledger" / "fragments"
        assert not fragment_dir.exists()
    else:
        raise AssertionError("expected validation error")
