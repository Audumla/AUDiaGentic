"""Unit tests for foundation/workflow/propagation/log.py."""

from __future__ import annotations

import json
from pathlib import Path

from audiagentic.foundation.workflow.propagation.log import PropagationLog


def _log(path: Path | None) -> PropagationLog:
    return PropagationLog(path)


def _entry(log: PropagationLog, path: Path | None = None, **overrides) -> None:
    kwargs = dict(
        status="success",
        target_id="t-1",
        target_state="done",
        source_id="s-1",
        source_kind="task",
        source_state="active",
        metadata={},
    )
    kwargs.update(overrides)
    log.append(**kwargs)


# ── no-op when path is None ───────────────────────────────────────────────────

def test_none_path_is_noop() -> None:
    log = _log(None)
    _entry(log)  # must not raise


# ── creates file and parent dirs ──────────────────────────────────────────────

def test_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "log.json"
    log = _log(path)
    _entry(log)
    assert path.exists()


def test_creates_list_on_first_write(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    _log(path)
    _entry(_log(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1


# ── append behaviour ─────────────────────────────────────────────────────────

def test_appends_to_existing_list(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    for _ in range(3):
        _entry(_log(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 3


def test_entry_fields_present(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    _entry(
        _log(path),
        status="skipped",
        target_id="t-2",
        target_state="done",
        source_id="s-2",
        source_kind="task",
        source_state="active",
        target_kind="wp",
        old_state="active",
        reason="already_in_target_state",
        metadata={"correlation_id": "corr-1", "propagation_depth": 2},
    )
    entry = json.loads(path.read_text(encoding="utf-8"))[0]
    assert entry["status"] == "skipped"
    assert entry["target_id"] == "t-2"
    assert entry["old_state"] == "active"
    assert entry["reason"] == "already_in_target_state"
    assert entry["correlation_id"] == "corr-1"
    assert entry["propagation_depth"] == 2


def test_reason_omitted_when_none(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    _entry(_log(path), reason=None)
    entry = json.loads(path.read_text(encoding="utf-8"))[0]
    assert "reason" not in entry


# ── corrupt existing file recovery ───────────────────────────────────────────

def test_recovers_from_non_list_json(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    path.write_text('{"broken": true}', encoding="utf-8")
    _entry(_log(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1


def test_recovers_from_truncated_file(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    path.write_text("[{bad json", encoding="utf-8")
    _entry(_log(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)


# ── unicode survives round-trip ───────────────────────────────────────────────

def test_unicode_in_ids(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    _entry(_log(path), target_id="tâche-1", source_id="source-日本語")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["target_id"] == "tâche-1"
    assert data[0]["source_id"] == "source-日本語"


# ── metadata correlation fields ───────────────────────────────────────────────

def test_event_id_from_event_id_key(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    _entry(_log(path), metadata={"event_id": "ev-42"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["event_id"] == "ev-42"


def test_correlation_id_preferred_over_event_id(tmp_path: Path) -> None:
    path = tmp_path / "log.json"
    _entry(_log(path), metadata={"correlation_id": "corr-1", "event_id": "ev-2"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["event_id"] == "corr-1"
