"""Job record contract helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError

REPO_ROOT = Path(__file__).resolve().parents[4]
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
    model_id: str | None = None
    model_alias: str | None = None
    default_model: str | None = None
    launch_source: dict[str, Any] | None = None
    launch_tag: str | None = None
    launch_target: dict[str, Any] | None = None
    review_policy: dict[str, Any] | None = None
    review_bundle_id: str | None = None


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
    model_id: str | None = None,
    model_alias: str | None = None,
    default_model: str | None = None,
    launch_source: dict[str, Any] | None = None,
    launch_tag: str | None = None,
    launch_target: dict[str, Any] | None = None,
    review_policy: dict[str, Any] | None = None,
    review_bundle_id: str | None = None,
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
    if model_id is not None:
        payload["model-id"] = model_id
    if model_alias is not None:
        payload["model-alias"] = model_alias
    if default_model is not None:
        payload["default-model"] = default_model
    if launch_source is not None:
        payload["launch-source"] = launch_source
    if launch_tag is not None:
        payload["launch-tag"] = launch_tag
    if launch_target is not None:
        payload["launch-target"] = launch_target
    if review_policy is not None:
        payload["review-policy"] = review_policy
    if review_bundle_id is not None:
        payload["review-bundle-id"] = review_bundle_id
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
        model_id=payload.get("model-id"),
        model_alias=payload.get("model-alias"),
        default_model=payload.get("default-model"),
        launch_source=payload.get("launch-source"),
        launch_tag=payload.get("launch-tag"),
        launch_target=payload.get("launch-target"),
        review_policy=payload.get("review-policy"),
        review_bundle_id=payload.get("review-bundle-id"),
    )
