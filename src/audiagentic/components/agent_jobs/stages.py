"""Stage execution contract and persistence."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)
from audiagentic.foundation.io import atomic_write_json

StageHandler = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None],
    dict[str, Any],
]

STAGE_RESULTS = {"success", "failure", "skipped"}
NEXT_STAGE_RECOMMENDATIONS = {"continue", "stop", "escalate"}


def _stage_dir(project_root: Path, job_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id / "stages"


def stage_output_path(project_root: Path, job_id: str, stage_id: str) -> Path:
    return _stage_dir(project_root, job_id) / f"{stage_id}.json"


def _validate_stage_output(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if payload.get("stage-result") not in STAGE_RESULTS:
        issues.append("stage-result must be success, failure, or skipped")
    if payload.get("next-stage-recommendation") not in NEXT_STAGE_RECOMMENDATIONS:
        issues.append("next-stage-recommendation must be continue, stop, or escalate")
    if "artifacts" not in payload or not isinstance(payload.get("artifacts"), list):
        issues.append("artifacts must be a list")
    if "warnings" in payload and not isinstance(payload.get("warnings"), list):
        issues.append("warnings must be a list")
    return issues



def execute_stage(
    project_root: Path,
    *,
    job_record: dict[str, Any],
    stage: dict[str, Any],
    packet_ctx: dict[str, Any],
    handler: StageHandler,
    previous_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output = handler(job_record, stage, packet_ctx, previous_output)
    issues = _validate_stage_output(output)
    if issues:
        raise AudiaGenticError(
            code="VAL-STAGE-001",
            kind="agent-jobs",
            message="stage output failed validation",
            details={"issues": issues, "stage-id": stage.get("id")},
        )
    stage_id = stage.get("id")
    if not isinstance(stage_id, str):
        raise AudiaGenticError(
            code="VAL-STAGE-002",
            kind="agent-jobs",
            message="stage missing valid id",
            details={"stage": stage},
        )
    envelope = {
        "contract-version": "v1",
        "stage-id": stage_id,
        "input": {
            "job-record-id": job_record.get("job-id"),
            "packet-id": job_record.get("packet-id"),
            "previous-stage-output": previous_output,
        },
        "output": output,
    }
    atomic_write_json(stage_output_path(project_root, job_record["job-id"], stage_id), envelope)
    return envelope
