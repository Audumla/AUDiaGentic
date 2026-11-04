from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.ledger import ledger_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


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


def test_record_change_writes_one_event_file_and_reports_pending(tmp_path: Path) -> None:
    result = ledger_api.record_change(tmp_path, _event("chg_one"))
    assert result["status"] == "created" and result["pending-count"] == 1
    assert Path(result["event-path"]).is_file()


def test_record_changes_records_each_event(tmp_path: Path) -> None:
    result = ledger_api.record_changes(tmp_path, [_event("chg_a"), _event("chg_b")])
    assert result["count"] == 2 and result["pending-count"] == 2
    assert len(list((tmp_path / "docs" / "releases" / "events").glob("*.json"))) == 2


def test_get_current_summary_renders_without_writing_a_tracked_file(tmp_path: Path) -> None:
    ledger_api.record_change(tmp_path, _event("chg_summary"))
    text = ledger_api.get_current_summary(tmp_path)
    assert "chg_summary" in text
    assert not (tmp_path / "docs" / "releases" / "CURRENT_RELEASE.md").exists()
    assert (tmp_path / ".audiagentic" / "runtime" / "ledger" / "generated" / "CURRENT_RELEASE.md").is_file()


def test_get_audit_report_writes_only_untracked_projections(tmp_path: Path) -> None:
    ledger_api.record_change(tmp_path, _event("chg_audit"))
    result = ledger_api.generate_audit(tmp_path)
    for key in ("audit-path", "checkin-path"):
        assert ".audiagentic/runtime/ledger/generated" in Path(result[key]).as_posix()
    assert not (tmp_path / "docs" / "releases" / "AUDIT_SUMMARY.md").exists()


def test_get_status_reports_event_counts(tmp_path: Path) -> None:
    ledger_api.record_change(tmp_path, _event("chg_status"))
    status = ledger_api.get_status(tmp_path)
    assert status["event-file-count"] == 1 and status["pending-count"] == 1


def test_sync_fails_closed_on_a_malformed_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(AudiaGenticError):
        ledger_api.sync(tmp_path)
