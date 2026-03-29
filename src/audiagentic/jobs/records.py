"""Job record contract helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "job-record.schema.json"


@dataclass(frozen=True)
class JobRecord:
    contract_version: str
    job_id: str
    packet_id: str
    project_id: str
    provider_id: str
    workflow_profile: str
    state: str
    created_at: str
    updated_at: str
    artifacts: list[dict[str, Any]]
    approvals: list[dict[str, Any]]


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_job_record(payload: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = [error.message for error in validator.iter_errors(payload)]
    return sorted(errors)


def build_job_record(
    *,
    job_id: str,
    packet_id: str,
    project_id: str,
    provider_id: str,
    workflow_profile: str,
    state: str = "created",
    created_at: str | None = None,
    updated_at: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    approvals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timestamp = _now_timestamp()
    payload = {
        "contract-version": "v1",
        "job-id": job_id,
        "packet-id": packet_id,
        "project-id": project_id,
        "provider-id": provider_id,
        "workflow-profile": workflow_profile,
        "state": state,
        "created-at": created_at or timestamp,
        "updated-at": updated_at or timestamp,
        "artifacts": artifacts or [],
        "approvals": approvals or [],
    }
    issues = validate_job_record(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-001",
            kind="validation",
            message="job record failed schema validation",
            details={"issues": issues},
        )
    return payload


def coerce_job_record(payload: dict[str, Any]) -> JobRecord:
    issues = validate_job_record(payload)
    if issues:
        raise AudiaGenticError(
            code="JOB-VALIDATION-002",
            kind="validation",
            message="job record failed schema validation",
            details={"issues": issues},
        )
    return JobRecord(
        contract_version=payload["contract-version"],
        job_id=payload["job-id"],
        packet_id=payload["packet-id"],
        project_id=payload["project-id"],
        provider_id=payload["provider-id"],
        workflow_profile=payload["workflow-profile"],
        state=payload["state"],
        created_at=payload["created-at"],
        updated_at=payload["updated-at"],
        artifacts=list(payload.get("artifacts", [])),
        approvals=list(payload.get("approvals", [])),
    )
