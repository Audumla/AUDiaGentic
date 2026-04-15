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

from tests.helpers import sandbox as sandbox_helper

from audiagentic.channels.cli.main import main
from audiagentic.execution.jobs.records import build_job_record
from audiagentic.runtime.state.jobs_store import read_job_record, write_job_record


def test_job_control_cli_cancels_ready_job(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-control-cli")
    try:
        job = build_job_record(
            job_id="job_20260330_0303",
            packet_id="pkt-job-011",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            state="ready",
            created_at="2026-03-30T00:00:00Z",
            updated_at="2026-03-30T00:00:00Z",
        )
        write_job_record(sandbox.repo, job)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(
                [
                    "job-control",
                    "--project-root",
                    str(sandbox.repo),
                    "--job-id",
                    job["job-id"],
                    "--action",
                    "cancel",
                    "--requested-by",
                    "operator",
                    "--reason",
                    "stop now",
                ]
            )
        assert exit_code == 0
        assert read_job_record(sandbox.repo, job["job-id"])["state"] == "cancelled"
        assert "applied" in buffer.getvalue()
    finally:
        sandbox.cleanup()
