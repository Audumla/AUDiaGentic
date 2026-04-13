from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.execution.jobs.release_bridge import build_change_event_from_job, emit_job_change
from audiagentic.execution.jobs.records import build_job_record
from audiagentic.runtime.state.jobs_store import write_job_record
from tests.helpers import sandbox as sandbox_helper


def test_release_bridge_emits_change_and_updates_docs(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "release-bridge")
    try:
        job = build_job_record(
            job_id="job_20260330_0301",
            packet_id="pkt-job-006",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            state="running",
            created_at="2026-03-30T00:00:00Z",
            updated_at="2026-03-30T00:00:00Z",
        )
        write_job_record(sandbox.repo, job)
        change_payload = {
            "event-id": "chg_job_0001",
            "change-class": "feature",
            "files": ["src/example.py"],
            "diff-stats": {"files-changed": 1, "insertions": 2, "deletions": 0},
            "technical-summary": "Added example feature.",
            "user-summary-candidate": "Added example feature.",
        }
        result = emit_job_change(sandbox.repo, job_record=job, change_payload=change_payload)
        assert result["event-id"] == "chg_job_0001"

        ledger = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        entries = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert entries[0]["event-id"] == "chg_job_0001"

        current_release = (sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE.md").read_text(
            encoding="utf-8"
        )
        assert "chg_job_0001" in current_release
        assert (sandbox.repo / "docs" / "releases" / "AUDIT_SUMMARY.md").exists()
        assert (sandbox.repo / "docs" / "releases" / "CHECKIN.md").exists()
    finally:
        sandbox.cleanup()


def test_release_bridge_requires_payload_fields() -> None:
    try:
        build_change_event_from_job(
            {"job-id": "job_1", "project-id": "my-project", "packet-id": "pkt", "provider-id": "local-openai"},
            {"event-id": "chg_1"},
        )
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected missing field error")
