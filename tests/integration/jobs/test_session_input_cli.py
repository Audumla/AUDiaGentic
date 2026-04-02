from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.channels.cli.main import main
from audiagentic.execution.jobs.records import build_job_record
from audiagentic.execution.jobs.store import write_job_record
from tests.helpers import sandbox as sandbox_helper


def test_session_input_cli_records_input_artifacts(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "session-input-cli")
    try:
        job = build_job_record(
            job_id="job_20260331_0401",
            packet_id="pkt-job-011",
            project_id="my-project",
            provider_id="cline",
            workflow_profile="standard",
            state="running",
            created_at="2026-03-31T00:00:00Z",
            updated_at="2026-03-31T00:00:00Z",
        )
        write_job_record(sandbox.repo, job)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(
                [
                    "session-input",
                    "--project-root",
                    str(sandbox.repo),
                    "--job-id",
                    job["job-id"],
                    "--provider-id",
                    "cline",
                    "--surface",
                    "cli",
                    "--stage",
                    "running",
                    "--message",
                    "Please continue from the previous step.",
                ],
                )
        assert exit_code == 0
        output = buffer.getvalue()
        assert "\"status\": \"recorded\"" in output
        input_path = sandbox.repo / ".audiagentic" / "runtime" / "jobs" / job["job-id"] / "input.ndjson"
        stdin_log = sandbox.repo / ".audiagentic" / "runtime" / "jobs" / job["job-id"] / "stdin.log"
        events_path = sandbox.repo / ".audiagentic" / "runtime" / "jobs" / job["job-id"] / "input-events.ndjson"
        assert input_path.exists()
        assert stdin_log.exists()
        assert events_path.exists()
        assert "Please continue from the previous step." in stdin_log.read_text(encoding="utf-8")
    finally:
        sandbox.cleanup()
