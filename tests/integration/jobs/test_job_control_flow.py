from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.helpers import sandbox as sandbox_helper

from audiagentic.execution.jobs import control as job_control
from audiagentic.execution.jobs.packet_runner import run_packet
from audiagentic.execution.jobs.records import build_job_record
from audiagentic.runtime.state.jobs_store import read_job_record, write_job_record


def test_request_job_control_cancels_ready_job(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-control-ready")
    try:
        job = build_job_record(
            job_id="job_20260330_0301",
            packet_id="pkt-job-011",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            state="ready",
            created_at="2026-03-30T00:00:00Z",
            updated_at="2026-03-30T00:00:00Z",
        )
        write_job_record(sandbox.repo, job)
        control = job_control.build_job_control_request(
            job_id=job["job-id"],
            project_id="my-project",
            requested_action="cancel",
            requested_by="operator",
            reason="user requested stop",
            requested_at="2026-03-30T00:01:00Z",
        )
        applied = job_control.request_job_control(sandbox.repo, control)
        assert applied["result"] == "applied"
        assert read_job_record(sandbox.repo, job["job-id"])["state"] == "cancelled"
        assert (
            sandbox.repo
            / ".audiagentic"
            / "runtime"
            / "jobs"
            / job["job-id"]
            / "job-control.json"
        ).exists()
    finally:
        sandbox.cleanup()


def test_packet_runner_honors_pending_cancellation_between_stages(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-control-running")
    try:
        seen: list[str] = []

        def stage_handler(job, stage, ctx, previous_output):
            seen.append(stage["id"])
            if stage["id"] == "plan":
                request = job_control.build_job_control_request(
                    job_id=job["job-id"],
                    project_id=job["project-id"],
                    requested_action="cancel",
                    requested_by="operator",
                    reason="stop after plan",
                    requested_at="2026-03-30T00:01:00Z",
                )
                job_control.request_job_control(sandbox.repo, request)
            return {
                "stage-result": "success",
                "artifacts": [],
                "next-stage-recommendation": "continue",
            }

        result = run_packet(
            sandbox.repo,
            packet_id="pkt-job-003",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            job_id="job_20260330_0302",
            stage_handler=stage_handler,
            now_fn=lambda: "2026-03-30T00:00:00Z",
        )
        assert result["state"] == "cancelled"
        assert seen == ["plan"]
    finally:
        sandbox.cleanup()
