from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.ledger import recorder
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


def test_recording_an_existing_event_is_idempotent_and_never_touches_a_plan_file(tmp_path: Path):
    event = _event()
    path = tmp_path / "docs" / "releases" / "events" / event_file_name("chg_existing")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(event), encoding="utf-8")
    plan = tmp_path / "docs" / "planning" / "active" / "p" / "TST01.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("original\n", encoding="utf-8")

    result = recorder.record_change_event(tmp_path, dict(event))

    assert result["status"] == "exists"
    assert plan.read_text(encoding="utf-8") == "original\n"  # a plan-item link is derived, never written


def test_a_crash_while_writing_leaves_no_visible_event_and_the_retry_succeeds(tmp_path: Path, monkeypatch):
    from audiagentic.components.ledger import current_events

    real = current_events.atomic_write_text

    def crash(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(current_events, "atomic_write_text", crash)
    try:
        recorder.record_change_event(tmp_path, _event())
    except RuntimeError:
        pass
    events = tmp_path / "docs" / "releases" / "events"
    assert not events.exists() or not list(events.glob("*.json"))  # nothing partial is visible
    monkeypatch.setattr(current_events, "atomic_write_text", real)

    assert recorder.record_change_event(tmp_path, _event())["status"] == "created"  # the caller retries
    assert recorder.record_change_event(tmp_path, _event())["status"] == "exists"  # a replay after success is idempotent
    changed = {**_event(), "technical-summary": "different"}
    try:
        recorder.record_change_event(tmp_path, changed)
    except Exception as error:
        assert "different content" in str(error)
    else:
        raise AssertionError("a conflicting retry must fail")


def test_the_event_lock_directory_follows_the_configured_ledger_runtime_path(tmp_path: Path):
    config = tmp_path / ".audiagentic" / "components" / "agent-ledger.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("paths:\n  ledger-runtime: .audiagentic/runtime/custom-ledger\n", encoding="utf-8")

    recorder.record_change_event(tmp_path, _event())

    assert (tmp_path / ".audiagentic" / "runtime" / "custom-ledger" / "event-locks").is_dir()
    assert not (tmp_path / ".audiagentic" / "runtime" / "ledger" / "event-locks").exists()
