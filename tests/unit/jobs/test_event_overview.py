"""Tests for the event-jobs operator overview (EDJ14)."""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.agent_jobs.event_overview import event_jobs_overview
from audiagentic.components.agent_jobs.jobs_store import write_job_record

_AUDIT_REL = Path(".audiagentic") / "runtime" / "agent-jobs" / "trigger-audit.ndjson"


def _write_audit(project_root: Path, entries: list[dict]) -> None:
    path = project_root / _AUDIT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )


def _audit_entry(
    trigger_id: str = "t-1",
    status: str = "fired",
    timestamp: str = "2026-01-01T00:00:00Z",
    **extra,
) -> dict:
    entry = {
        "timestamp": timestamp,
        "trigger_id": trigger_id,
        "event_type": "planning.item.created",
        "correlation_id": "corr-1",
        "status": status,
        "job_id": None,
        "error_code": None,
        "error_message": None,
    }
    entry.update(extra)
    return entry


def _write_job(project_root: Path, job_id: str, state: str, event_source: dict | None) -> None:
    now = "2025-01-01T00:00:00Z"
    record = {
        "contract-version": "v1",
        "job-id": job_id,
        "project-id": "test-project",
        "provider-id": "local-openai",
        "workflow-profile": "standard",
        "state": state,
        "packet-id": "adhoc",
        "created-at": now,
        "updated-at": now,
        "artifacts": [],
        "approvals": [],
    }
    if event_source is not None:
        record["event-source"] = event_source
    write_job_record(project_root, record)


_EVENT_SOURCE = {
    "event-type": "planning.item.created",
    "trigger-id": "t-1",
    "correlation-id": "corr-1",
    "subject": None,
    "source-component": "planning",
    "occurred-at": "2026-01-01T00:00:00Z",
}


class TestEmptyState:
    def test_missing_everything_returns_empty_shape(self, tmp_path: Path) -> None:
        overview = event_jobs_overview(tmp_path)
        assert overview == {
            "by_trigger": {},
            "jobs_by_state": {},
            "recent_failures": [],
        }


class TestTriggerAggregation:
    def test_counts_by_trigger_and_status(self, tmp_path: Path) -> None:
        _write_audit(tmp_path, [
            _audit_entry("t-1", "fired"),
            _audit_entry("t-1", "fired"),
            _audit_entry("t-1", "failed", error_code="INT-EVT-001", error_message="boom"),
            _audit_entry("t-2", "suppressed"),
        ])

        overview = event_jobs_overview(tmp_path)
        assert overview["by_trigger"] == {
            "t-1": {"fired": 2, "suppressed": 0, "failed": 1},
            "t-2": {"fired": 0, "suppressed": 1, "failed": 0},
        }

    def test_unknown_statuses_ignored(self, tmp_path: Path) -> None:
        _write_audit(tmp_path, [
            _audit_entry("t-1", "fired"),
            _audit_entry("t-1", "outcome"),  # obsolete field value shape
            _audit_entry("t-1", "bogus"),
        ])
        overview = event_jobs_overview(tmp_path)
        assert overview["by_trigger"] == {"t-1": {"fired": 1, "suppressed": 0, "failed": 0}}

    def test_malformed_audit_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / _AUDIT_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json\n{broken", encoding="utf-8")

        overview = event_jobs_overview(tmp_path)
        assert overview["by_trigger"] == {}
        assert overview["recent_failures"] == []


class TestRecentFailures:
    def test_newest_first_capped_at_five_and_redacted(self, tmp_path: Path) -> None:
        entries = [
            _audit_entry(
                f"t-{i}",
                "failed",
                timestamp=f"2026-01-0{i}T00:00:00Z",
                error_code="INT-EVT-001",
                error_message=f"failure {i} password=hunter2secret",
            )
            for i in range(1, 8)
        ]
        _write_audit(tmp_path, entries)

        failures = event_jobs_overview(tmp_path)["recent_failures"]
        assert len(failures) == 5
        assert [f["trigger_id"] for f in failures] == ["t-7", "t-6", "t-5", "t-4", "t-3"]
        for f in failures:
            assert set(f) == {
                "trigger_id", "event_type", "correlation_id", "error_code", "error_message",
            }
            assert "hunter2secret" not in f["error_message"], "error message must be redacted"


class TestJobsByState:
    def test_counts_only_event_origin_jobs(self, tmp_path: Path) -> None:
        _write_job(tmp_path, "job-evt-1", "running", _EVENT_SOURCE)
        _write_job(tmp_path, "job-evt-2", "completed", _EVENT_SOURCE)
        _write_job(tmp_path, "job-evt-3", "completed", _EVENT_SOURCE)
        _write_job(tmp_path, "job-direct", "running", None)

        overview = event_jobs_overview(tmp_path)
        assert overview["jobs_by_state"] == {"running": 1, "completed": 2}


class TestMcpWrapper:
    def test_tool_registered_and_returns_shape(self, tmp_path: Path, monkeypatch) -> None:
        from audiagentic.components.agent_jobs import jobs_mcp

        monkeypatch.setattr(jobs_mcp, "project_root_from_env", lambda: tmp_path)
        result = jobs_mcp.event_jobs_overview_tool()
        assert set(result) == {"by_trigger", "jobs_by_state", "recent_failures"}
