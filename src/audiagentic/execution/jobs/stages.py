"""Stage execution contract and persistence."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from audiagentic.foundation.contracts.errors import AudiaGenticError

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


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
            code="JOB-VALIDATION-017",
            kind="validation",
            message="stage output failed validation",
            details={"issues": issues, "stage-id": stage.get("id")},
        )
    envelope = {
        "contract-version": "v1",
        "stage-id": stage.get("id"),
        "input": {
            "job-record-id": job_record.get("job-id"),
            "packet-id": job_record.get("packet-id"),
            "previous-stage-output": previous_output,
        },
        "output": output,
    }
    _write_atomic(stage_output_path(project_root, job_record["job-id"], stage.get("id")), envelope)
    return envelope
