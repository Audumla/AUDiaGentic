"""Unit tests for event_state module."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from audiagentic.knowledge.config import load_config
from audiagentic.knowledge.event_state import (
    _fingerprint_text,
    _lookup_dotted,
    _matches_payload_filters,
    load_event_state,
    prune_event_state,
    save_event_state,
)

ROOT = Path(__file__).resolve().parents[3]


def _seed_project(root: Path) -> None:
    shutil.copytree(ROOT / ".audiagentic" / "knowledge", root / ".audiagentic" / "knowledge", dirs_exist_ok=True)
    state_dir = root / "docs" / "knowledge" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "event-state.yml").write_text(
        yaml.safe_dump({"sources": {}, "processed_event_ids": []}, sort_keys=False),
        encoding="utf-8",
    )


# --- load_event_state / save_event_state ---

def test_load_event_state_defaults(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    state = load_event_state(config)
    assert "sources" in state
    assert "processed_event_ids" in state
    assert isinstance(state["sources"], dict)
    assert isinstance(state["processed_event_ids"], list)


def test_save_and_reload_event_state(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    state = load_event_state(config)
    state["processed_event_ids"] = ["event-001", "event-002"]
    state["sources"]["some/path.md"] = {"fingerprint": "abc123"}
    save_event_state(config, state)

    reloaded = load_event_state(config)
    assert "event-001" in reloaded["processed_event_ids"]
    assert "event-002" in reloaded["processed_event_ids"]
    assert reloaded["sources"]["some/path.md"]["fingerprint"] == "abc123"


def test_save_event_state_prunes_when_over_limit(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    state = {"sources": {}, "processed_event_ids": [f"event-{i}" for i in range(1200)]}
    # Set max_processed_events low
    config.raw.setdefault("events", {})["max_processed_events"] = 100
    save_event_state(config, state)

    reloaded = load_event_state(config)
    assert len(reloaded["processed_event_ids"]) == 100


# --- prune_event_state ---

def test_prune_event_state_removes_old_ids(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    state = {"sources": {}, "processed_event_ids": [f"event-{i}" for i in range(50)]}
    save_event_state(config, state)

    result = prune_event_state(config, max_events=20)
    assert result["ok"] is True
    assert result["pruned_state"] == 30
    assert result["remaining"] == 20


def test_prune_event_state_no_prune_needed(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    state = {"sources": {}, "processed_event_ids": ["event-1", "event-2"]}
    save_event_state(config, state)

    result = prune_event_state(config, max_events=1000)
    assert result["pruned_state"] == 0
    assert result["remaining"] == 2


def test_prune_event_state_prunes_journal(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    config.event_journal_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"event_id": f"event-{i}"}) for i in range(50)]
    config.event_journal_file.write_text("\n".join(lines), encoding="utf-8")

    result = prune_event_state(config, max_events=20)
    assert result["pruned_journal"] == 30
    remaining_lines = config.event_journal_file.read_text().splitlines()
    assert len(remaining_lines) == 20


# --- _fingerprint_text ---

def test_fingerprint_text_is_deterministic():
    text = "hello world"
    assert _fingerprint_text(text) == _fingerprint_text(text)


def test_fingerprint_text_differs_for_different_input():
    assert _fingerprint_text("hello") != _fingerprint_text("world")


def test_fingerprint_text_is_sha256_hex():
    result = _fingerprint_text("test")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# --- _lookup_dotted ---

def test_lookup_dotted_top_level():
    data = {"status": "done"}
    assert _lookup_dotted(data, "status") == "done"


def test_lookup_dotted_nested():
    data = {"payload": {"state": "active"}}
    assert _lookup_dotted(data, "payload.state") == "active"


def test_lookup_dotted_missing_key():
    data = {"payload": {}}
    assert _lookup_dotted(data, "payload.missing") is None


def test_lookup_dotted_empty_path():
    data = {"a": 1}
    result = _lookup_dotted(data, "")
    # Empty path returns the whole dict
    assert result == data


# --- _matches_payload_filters ---

def test_matches_payload_filters_equals_match():
    raw = {"status": "done"}
    assert _matches_payload_filters(raw, {"equals": {"status": "done"}})


def test_matches_payload_filters_equals_no_match():
    raw = {"status": "pending"}
    assert not _matches_payload_filters(raw, {"equals": {"status": "done"}})


def test_matches_payload_filters_in_match():
    raw = {"status": "done"}
    assert _matches_payload_filters(raw, {"in": {"status": ["done", "verified"]}})


def test_matches_payload_filters_in_no_match():
    raw = {"status": "pending"}
    assert not _matches_payload_filters(raw, {"in": {"status": ["done", "verified"]}})


def test_matches_payload_filters_contains_any_match():
    raw = {"message": "task completed successfully"}
    assert _matches_payload_filters(raw, {"contains_any": {"message": ["completed", "failed"]}})


def test_matches_payload_filters_contains_any_no_match():
    raw = {"message": "task still running"}
    assert not _matches_payload_filters(raw, {"contains_any": {"message": ["completed", "failed"]}})


def test_matches_payload_filters_empty_filters():
    raw = {"anything": "here"}
    assert _matches_payload_filters(raw, {})
