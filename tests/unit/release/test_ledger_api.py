from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.ledger import ledger_api
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_text


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


def test_record_change_can_skip_sync(tmp_path: Path) -> None:
    result = ledger_api.record_change(tmp_path, _event("chg_skip_sync"), sync=False)
    assert result["status"] == "created"
    assert "ledger-count" not in result


def test_record_changes_can_batch_without_sync(tmp_path: Path) -> None:
    result = ledger_api.record_changes(
        tmp_path,
        [_event("chg_batch_001"), _event("chg_batch_002")],
        sync=False,
    )

    assert result["count"] == 2
    assert "ledger-count" not in result
    ledger_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    assert not ledger_path.exists()


def test_record_changes_syncs_once_at_end(tmp_path: Path) -> None:
    result = ledger_api.record_changes(
        tmp_path,
        [_event("chg_batch_sync_001"), _event("chg_batch_sync_002")],
        sync=True,
    )

    assert result["count"] == 2
    assert result["ledger-count"] == 2
    ledger_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2


def test_get_current_summary_does_not_rewrite_existing_summary(tmp_path: Path) -> None:
    summary_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE.md"
    atomic_write_text(summary_path, "cached summary\n")
    before = summary_path.stat().st_mtime_ns

    content = ledger_api.get_current_summary(tmp_path)
    after = summary_path.stat().st_mtime_ns

    assert content == "cached summary\n"
    assert after == before


def test_get_current_summary_generates_when_missing(tmp_path: Path) -> None:
    ledger_api.record_change(tmp_path, _event("chg_generate_summary"), sync=True)
    content = ledger_api.get_current_summary(tmp_path)
    assert "# Current Release" in content


def test_get_status_tolerates_invalid_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / ".audiagentic" / "runtime" / "ledger" / "sync" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{not-json", encoding="utf-8")

    status = ledger_api.get_status(tmp_path)
    assert status["last-synced"] is None


def test_record_change_default_no_sync(tmp_path: Path) -> None:
    result = ledger_api.record_change(tmp_path, _event("chg_default_no_sync"))
    assert result["status"] == "created"
    assert "ledger-count" not in result
    ledger_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    assert not ledger_path.exists()


def test_incremental_sync_appends_only(tmp_path: Path) -> None:
    ledger_api.record_changes(
        tmp_path,
        [_event("chg_inc_001"), _event("chg_inc_002")],
        sync=True,
    )
    ledger_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    lines_before = ledger_path.read_text(encoding="utf-8")
    mtime_before = ledger_path.stat().st_mtime_ns

    ledger_api.record_change(tmp_path, _event("chg_inc_003"), sync=True)
    lines_after = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len([l for l in lines_after if l.strip()]) == 3

    ledger_api.sync(tmp_path)
    lines_noop = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len([l for l in lines_noop if l.strip()]) == 3


def test_empty_sync_preserves_manifest_for_later_incremental_append(tmp_path: Path) -> None:
    """A no-op sync must not make the next event replace the current ledger."""
    ledger_api.record_changes(
        tmp_path,
        [_event("chg_empty_sync_001"), _event("chg_empty_sync_002")],
        sync=True,
    )
    ledger_api.sync(tmp_path)

    ledger_api.record_change(tmp_path, _event("chg_empty_sync_003"), sync=True)

    ledger_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    assert {json.loads(line)["event-id"] for line in lines} == {
        "chg_empty_sync_001",
        "chg_empty_sync_002",
        "chg_empty_sync_003",
    }


def test_stale_empty_manifest_cannot_replace_existing_ledger(tmp_path: Path) -> None:
    """Existing ledger IDs protect history even when the manifest was reset."""
    ledger_api.record_changes(
        tmp_path,
        [_event("chg_stale_manifest_001"), _event("chg_stale_manifest_002")],
        sync=True,
    )
    manifest_path = tmp_path / ".audiagentic" / "runtime" / "ledger" / "sync" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fragment-ids"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    ledger_api.record_change(tmp_path, _event("chg_stale_manifest_003"), sync=True)

    ledger_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3


def test_malformed_current_ledger_fails_closed(tmp_path: Path) -> None:
    ledger_path = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("{not-json}\n", encoding="utf-8")
    ledger_api.record_change(tmp_path, _event("chg_malformed_ledger"), sync=False)

    with pytest.raises(AudiaGenticError) as error:
        ledger_api.sync(tmp_path)

    assert error.value.code == "CON-SYNCL-002"
    assert ledger_path.read_text(encoding="utf-8") == "{not-json}\n"


def test_sync_purges_synced_fragments(tmp_path: Path) -> None:
    fragments_dir = tmp_path / ".audiagentic" / "runtime" / "ledger" / "fragments"

    ledger_api.record_changes(
        tmp_path,
        [_event("chg_purge_001"), _event("chg_purge_002")],
        sync=True,
    )

    remaining = list(fragments_dir.glob("*.json"))
    assert len(remaining) == 0


def test_sync_reported_purged_count(tmp_path: Path) -> None:
    ledger_api.record_changes(
        tmp_path,
        [_event("chg_purge_count_001"), _event("chg_purge_count_002")],
        sync=False,
    )

    fragments_dir = tmp_path / ".audiagentic" / "runtime" / "ledger" / "fragments"
    assert len(list(fragments_dir.glob("*.json"))) == 2

    result = ledger_api.sync(tmp_path)
    assert result["purged-fragment-count"] == 2
    assert len(list(fragments_dir.glob("*.json"))) == 0


def test_sync_purges_stray_directories(tmp_path: Path) -> None:
    ledger_api.record_change(tmp_path, _event("chg_stray_001"), sync=True)

    fragments_dir = tmp_path / ".audiagentic" / "runtime" / "ledger" / "fragments"
    stray = fragments_dir / "bad-stray-dir"
    stray.mkdir(parents=True)
    assert stray.is_dir()

    ledger_api.record_change(tmp_path, _event("chg_stray_002"), sync=True)
    assert not stray.exists()
