from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.helpers import sandbox as sandbox_helper

from audiagentic.execution.jobs.stages import execute_stage, stage_output_path
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_stage_execution_persists_output(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "stage-contract")
    try:
        job = {
            "job-id": "job_20260330_0003",
            "packet-id": "pkt-job-004",
        }
        stage = {"id": "plan", "required": True}

        fixture = json.loads(
            (ROOT / "docs" / "examples" / "fixtures" / "stage-result.valid.json").read_text(
                encoding="utf-8"
            )
        )

        def handler(job_record, stage, ctx, previous_output):
            return fixture

        envelope = execute_stage(
            sandbox.repo,
            job_record=job,
            stage=stage,
            packet_ctx={"packet-id": "pkt-job-004"},
            handler=handler,
            previous_output=None,
        )
        path = stage_output_path(sandbox.repo, job["job-id"], stage["id"])
        assert path.exists()
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert persisted == envelope
    finally:
        sandbox.cleanup()


def test_stage_execution_rejects_invalid_output(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "stage-contract-invalid")
    try:
        job = {
            "job-id": "job_20260330_0004",
            "packet-id": "pkt-job-004",
        }
        stage = {"id": "plan", "required": True}

        fixture = json.loads(
            (ROOT / "docs" / "examples" / "fixtures" / "stage-result.invalid.json").read_text(
                encoding="utf-8"
            )
        )

        def handler(job_record, stage, ctx, previous_output):
            return fixture

        try:
            execute_stage(
                sandbox.repo,
                job_record=job,
                stage=stage,
                packet_ctx={},
                handler=handler,
                previous_output=None,
            )
        except AudiaGenticError as exc:
            assert exc.kind == "validation"
        else:
            raise AssertionError("expected validation error")
        path = stage_output_path(sandbox.repo, job["job-id"], stage["id"])
        assert not path.exists()
    finally:
        sandbox.cleanup()


def test_stage_execution_idempotent(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "stage-contract-idempotent")
    try:
        job = {
            "job-id": "job_20260330_0005",
            "packet-id": "pkt-job-004",
        }
        stage = {"id": "plan", "required": True}

        def handler(job_record, stage, ctx, previous_output):
            return {
                "stage-result": "success",
                "artifacts": [],
                "next-stage-recommendation": "continue",
                "warnings": [],
            }

        first = execute_stage(
            sandbox.repo,
            job_record=job,
            stage=stage,
            packet_ctx={},
            handler=handler,
            previous_output=None,
        )
        second = execute_stage(
            sandbox.repo,
            job_record=job,
            stage=stage,
            packet_ctx={},
            handler=handler,
            previous_output=None,
        )
        path = stage_output_path(sandbox.repo, job["job-id"], stage["id"])
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert first == second
        assert persisted == second
    finally:
        sandbox.cleanup()
