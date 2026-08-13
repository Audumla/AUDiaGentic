# ruff: noqa: E402, I001

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest

from tests.helpers import sandbox as sandbox_helper

from audiagentic.components.agent_jobs.jobs_store import job_record_path
from audiagentic.components.agent_jobs.packet_runner import run_packet
from audiagentic.components.agent_jobs.stages import stage_output_path
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_packet_runner_submits_canonical_work_when_context_is_provided(
    tmp_path: Path, monkeypatch
) -> None:
    sandbox = sandbox_helper.create(tmp_path, "packet-runner-work")
    try:
        calls: list[tuple[Path, str, dict, dict]] = []

        class Gateway:
            def submit_agent_work(self, root, context_id, message, **kwargs):
                calls.append((root, context_id, message, kwargs))
                return {
                    "work_id": "work_packet_1",
                    "context_id": context_id,
                    "state": "active",
                }

        monkeypatch.setattr(
            "audiagentic.components.agents.gateway.client.get_gateway_client",
            lambda root: Gateway(),
        )

        result = run_packet(
            sandbox.repo,
            packet_id="pkt-work-001",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            context_id="ctx-packet-1",
            overrides={"stage-timeout-seconds": 30},
        )

        assert result["state"] == "active"
        assert len(calls) == 1
        root, context_id, message, kwargs = calls[0]
        assert root == sandbox.repo
        assert context_id == "ctx-packet-1"
        assert message["message_id"] == "packet:pkt-work-001"
        assert message["inputs"] == {
            "packet-id": "pkt-work-001",
            "project-id": "my-project",
            "provider-id": "local-openai",
            "workflow-profile": "lite",
            "stage-timeout-seconds": 30,
        }
        assert kwargs["work_id"]
        assert not (sandbox.repo / ".audiagentic" / "runtime" / "jobs").exists()
    finally:
        sandbox.cleanup()


def test_packet_runner_rejects_legacy_callbacks_on_canonical_path(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "packet-runner-work-callback")
    try:
        with pytest.raises(AudiaGenticError, match="cannot use local stage"):
            run_packet(
                sandbox.repo,
                packet_id="pkt-work-002",
                project_id="my-project",
                provider_id="local-openai",
                workflow_profile="lite",
                context_id="ctx-packet-1",
                stage_handler=lambda *_args: {},
            )
    finally:
        sandbox.cleanup()


def test_packet_runner_executes_stages_in_order(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "packet-runner")
    try:
        seen: list[str] = []

        def stage_handler(job, stage, ctx, previous_output):
            seen.append(stage["id"])
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
            job_id="job_20260330_0001",
            stage_handler=stage_handler,
            now_fn=lambda: "2026-03-30T00:00:00Z",
        )
        assert seen == ["plan", "implement", "summary"]
        assert result["state"] == "completed"
        assert job_record_path(sandbox.repo, "job_20260330_0001").exists()
        for stage_id in seen:
            assert stage_output_path(sandbox.repo, "job_20260330_0001", stage_id).exists()
    finally:
        sandbox.cleanup()


def test_packet_runner_handles_required_stage_failure(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "packet-runner-failure")
    try:
        def stage_handler(job, stage, ctx, previous_output):
            if stage["id"] == "implement":
                return {
                    "stage-result": "failure",
                    "artifacts": [],
                    "next-stage-recommendation": "stop",
                }
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
            job_id="job_20260330_0002",
            stage_handler=stage_handler,
            now_fn=lambda: "2026-03-30T00:00:00Z",
        )
        assert result["state"] == "failed"
        assert not (
            sandbox.repo
            / ".audiagentic"
            / "runtime"
            / "jobs"
            / "job_20260330_0002"
            / "stages"
            / "summary.json"
        ).exists()
    finally:
        sandbox.cleanup()


def test_packet_runner_is_idempotent_for_repeat_runs(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "packet-runner-repeat")
    try:
        seen: list[str] = []

        def stage_handler(job, stage, ctx, previous_output):
            seen.append(stage["id"])
            return {
                "stage-result": "success",
                "artifacts": [],
                "next-stage-recommendation": "continue",
            }

        first = run_packet(
            sandbox.repo,
            packet_id="pkt-job-003",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            job_id="job_20260330_0003",
            stage_handler=stage_handler,
            now_fn=lambda: "2026-03-30T00:00:00Z",
        )
        second = run_packet(
            sandbox.repo,
            packet_id="pkt-job-003",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            job_id="job_20260330_0003",
            stage_handler=stage_handler,
            now_fn=lambda: "2026-03-30T00:00:00Z",
        )

        assert first["state"] == "completed"
        assert second["state"] == "completed"
        assert seen == ["plan", "implement", "summary", "plan", "implement", "summary"]
        stage_dir = (
            sandbox.repo
            / ".audiagentic"
            / "runtime"
            / "jobs"
            / "job_20260330_0003"
            / "stages"
        )
        assert len(list(stage_dir.glob("*.json"))) == 3
    finally:
        sandbox.cleanup()
