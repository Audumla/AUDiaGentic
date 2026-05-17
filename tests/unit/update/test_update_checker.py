"""Unit tests for the update checker module."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from audiagentic.runtime.update.checker import (
    _version_tuple,
    check_update,
    current_version,
    skip_version,
)

# ── version tuple ─────────────────────────────────────────────────────────────

def test_version_tuple_basic():
    assert _version_tuple("1.2.3") == (1, 2, 3)


def test_version_tuple_comparison():
    assert _version_tuple("0.1.2") < _version_tuple("0.2.0")
    assert _version_tuple("1.0.0") > _version_tuple("0.9.9")


def test_version_tuple_malformed_returns_zero():
    assert _version_tuple("bad") == (0,)


# ── current_version ───────────────────────────────────────────────────────────

def test_current_version_returns_string():
    v = current_version()
    assert isinstance(v, str)
    assert len(v) > 0


# ── check_update — cache hit, no network ─────────────────────────────────────

def test_check_update_cached_result_no_network(tmp_path):
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cache = {
        "checked_at": recent,
        "latest_version": "99.0.0",
        "skipped_versions": [],
    }
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text(json.dumps(cache))

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        with patch("audiagentic.runtime.update.checker.current_version", return_value="0.1.0"):
            result = check_update()

    assert result is not None
    assert result["latest"] == "99.0.0"
    assert result["current"] == "0.1.0"


def test_check_update_no_update_when_up_to_date(tmp_path):
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cache = {"checked_at": recent, "latest_version": "0.1.0", "skipped_versions": []}
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text(json.dumps(cache))

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        with patch("audiagentic.runtime.update.checker.current_version", return_value="0.1.0"):
            result = check_update()

    assert result is None


def test_check_update_skipped_version_returns_none(tmp_path):
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cache = {
        "checked_at": recent,
        "latest_version": "99.0.0",
        "skipped_versions": ["99.0.0"],
    }
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text(json.dumps(cache))

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        with patch("audiagentic.runtime.update.checker.current_version", return_value="0.1.0"):
            result = check_update()

    assert result is None


# ── check_update — stale cache, hits network ─────────────────────────────────

def test_check_update_stale_cache_fetches_network(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    cache = {"checked_at": old, "latest_version": "0.1.0", "skipped_versions": []}
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text(json.dumps(cache))

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        with patch("audiagentic.runtime.update.checker.current_version", return_value="0.1.0"):
            with patch("audiagentic.runtime.update.checker.fetch_latest_version", return_value="99.0.0") as mock_fetch:
                result = check_update()

    mock_fetch.assert_called_once()
    assert result is not None
    assert result["latest"] == "99.0.0"


def test_check_update_network_failure_returns_none(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    cache = {"checked_at": old}
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text(json.dumps(cache))

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        with patch("audiagentic.runtime.update.checker.fetch_latest_version", return_value=None):
            result = check_update()

    assert result is None


# ── force=True bypasses cache ─────────────────────────────────────────────────

def test_check_update_force_bypasses_recent_cache(tmp_path):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    cache = {"checked_at": recent, "latest_version": "0.1.0", "skipped_versions": []}
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text(json.dumps(cache))

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        with patch("audiagentic.runtime.update.checker.current_version", return_value="0.1.0"):
            with patch("audiagentic.runtime.update.checker.fetch_latest_version", return_value="99.0.0") as mock_fetch:
                result = check_update(force=True)

    mock_fetch.assert_called_once()
    assert result is not None


# ── skip_version ──────────────────────────────────────────────────────────────

def test_skip_version_persists(tmp_path):
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text("{}")

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        skip_version("1.2.3")
        data = json.loads(cache_file.read_text())

    assert "1.2.3" in data["skipped_versions"]


def test_skip_version_no_duplicates(tmp_path):
    cache_file = tmp_path / "update-check.json"
    cache_file.write_text("{}")

    with patch("audiagentic.runtime.update.checker._cache_path", return_value=cache_file):
        skip_version("1.2.3")
        skip_version("1.2.3")
        data = json.loads(cache_file.read_text())

    assert data["skipped_versions"].count("1.2.3") == 1
