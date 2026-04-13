"""Job record persistence helpers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema


def validate_job_record(payload: dict[str, Any]) -> list[str]:
    schema = read_schema("job-record")
    validator = Draft202012Validator(schema)
    errors = [error.message for error in validator.iter_errors(payload)]
    return sorted(errors)


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
            code="JOB-IO-001",
            kind="io",
            message="failed to read job record",
            details={"job-id": job_id, "error": str(exc)},
        ) from exc
    issues = validate_job_record(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-003",
            kind="validation",
            message="job record failed schema validation",
            details={"job-id": job_id, "issues": issues},
        )
    return payload


def write_job_record(project_root: Path, payload: dict[str, Any]) -> Path:
    job_id = payload.get("job-id")
    if not job_id:
        raise AudiaGenticError(
            code="JOB-VALIDATION-004",
            kind="validation",
            message="job record missing job-id",
            details={},
        )
    issues = validate_job_record(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-005",
            kind="validation",
            message="job record failed schema validation",
            details={"job-id": job_id, "issues": issues},
        )

    target_dir = job_dir(project_root, job_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "job.json"

    fd, tmp_path = tempfile.mkstemp(prefix="job.", suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return target_path


def save_job_record(project_root: Path, payload: dict[str, Any]) -> Path:
    return write_job_record(project_root, payload)
