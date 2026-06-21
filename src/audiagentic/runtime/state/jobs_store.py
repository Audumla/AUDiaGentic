"""Job record persistence helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json


def validate_job_record(payload: dict[str, Any]) -> list[str]:
    return validate_with_schema("job-record", payload)


def _jobs_root(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs"


def job_dir(project_root: Path, job_id: str) -> Path:
    return _jobs_root(project_root) / job_id


def job_record_path(project_root: Path, job_id: str) -> Path:
    return job_dir(project_root, job_id) / "job.json"


def read_job_record(project_root: Path, job_id: str) -> dict[str, Any]:
    path = job_record_path(project_root, job_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-JOBSTORE-001",
            kind="state-store",
            message="failed to read job record",
            details={"job-id": job_id, "error": str(exc)},
        ) from exc
    issues = validate_job_record(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-JOBSTORE-001",
            kind="state-store",
            message="job record failed schema validation",
            details={"job-id": job_id, "issues": issues},
        )
    return payload


def write_job_record(project_root: Path, payload: dict[str, Any]) -> Path:
    job_id = payload.get("job-id")
    if not job_id:
        raise AudiaGenticError(
            code="VAL-JOBSTORE-002",
            kind="state-store",
            message="job record missing job-id",
            details={},
        )
    issues = validate_job_record(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-JOBSTORE-003",
            kind="state-store",
            message="job record failed schema validation",
            details={"job-id": job_id, "issues": issues},
        )

    target_path = job_dir(project_root, job_id) / "job.json"
    atomic_write_json(target_path, payload)
    return target_path
