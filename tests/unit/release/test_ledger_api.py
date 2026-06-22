from __future__ import annotations

from pathlib import Path

from audiagentic.components.ledger import ledger_api
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
