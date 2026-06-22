"""Structured review report and bundle helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_iso_z


def _validate(schema_name: str, payload: dict[str, Any]) -> list[str]:
    return validate_with_schema(schema_name, payload)


def validate_review_report(payload: dict[str, Any]) -> list[str]:
    return _validate("review-report", payload)


def validate_review_bundle(payload: dict[str, Any]) -> list[str]:
    return _validate("review-bundle", payload)


def reviewer_key_from_source(source: dict[str, Any]) -> str:
    return ":".join(
        [
            str(source.get("provider-id") or "unknown"),
            str(source.get("surface") or "unknown"),
            str(source.get("session-id") or "unknown"),
        ]
    )


def subject_from_target(target: dict[str, Any], *, existing_job_id: str | None = None) -> dict[str, Any]:
    kind = target["kind"]
    if kind == "packet":
        return {"kind": "packet", "packet-id": target["packet-id"]}
    if kind == "job":
        return {"kind": "job", "job-id": target["job-id"]}
    if kind == "artifact":
        subject: dict[str, Any] = {"kind": "artifact"}
        if existing_job_id:
            subject["job-id"] = existing_job_id
        if "artifact-id" in target:
            subject["artifact-id"] = target["artifact-id"]
        if "artifact-path" in target:
            subject["artifact-id"] = target["artifact-path"]
        return subject
    if kind == "adhoc":
        subject = {"kind": "adhoc"}
        if "adhoc-id" in target:
            subject["adhoc-id"] = target["adhoc-id"]
        return subject
    raise AudiaGenticError(
        code="VAL-REVIEW-001",
        kind="agent-jobs",
        message="unsupported review target kind",
        details={"kind": kind},
    )


def build_review_report(
    *,
    review_id: str,
    subject: dict[str, Any],
    reviewer: dict[str, Any],
    criteria: list[str],
    findings: list[dict[str, Any]],
    recommendation: str,
    follow_up_actions: list[str],
    created_at: str | None = None,
) -> dict[str, Any]:
    payload = {
        "contract-version": "v1",
        "review-id": review_id,
        "subject": subject,
        "reviewer": reviewer,
        "criteria": criteria,
        "findings": findings,
        "recommendation": recommendation,
        "follow-up-actions": follow_up_actions,
        "created-at": created_at or now_iso_z(),
    }
    issues = validate_review_report(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-REVIEW-002",
            kind="agent-jobs",
            message="review report failed schema validation",
            details={"issues": issues, "review-id": review_id},
        )
    return payload


def build_review_bundle(
    *,
    review_bundle_id: str,
    subject: dict[str, Any],
    required_reviews: int,
    aggregation_rule: str,
    require_distinct_reviewers: bool,
    reports: list[dict[str, Any]],
    updated_at: str | None = None,
) -> dict[str, Any]:
    recommendations = [report["recommendation"] for report in reports]
    distinct_reviewers = {report["reviewer-key"] for report in reports}

    if len(reports) < required_reviews:
        decision = "pending"
        status = "open"
    elif aggregation_rule != "all-pass":
        raise AudiaGenticError(
            code="VAL-REVIEW-003",
            kind="agent-jobs",
            message="unsupported review aggregation rule",
            details={"aggregation-rule": aggregation_rule},
        )
    elif require_distinct_reviewers and len(distinct_reviewers) < len(reports):
        decision = "pending"
        status = "open"
    elif any(recommendation == "block" for recommendation in recommendations):
        decision = "blocked"
        status = "complete"
    elif any(recommendation == "rework" for recommendation in recommendations):
        decision = "rework"
        status = "complete"
    elif all(recommendation in {"pass", "pass-with-notes"} for recommendation in recommendations):
        decision = "approved"
        status = "complete"
    else:
        decision = "pending"
        status = "open"

    payload = {
        "contract-version": "v1",
        "review-bundle-id": review_bundle_id,
        "subject": subject,
        "required-reviews": required_reviews,
        "aggregation-rule": aggregation_rule,
        "require-distinct-reviewers": require_distinct_reviewers,
        "reports": reports,
        "decision": decision,
        "status": status,
        "updated-at": updated_at or now_iso_z(),
    }
    issues = validate_review_bundle(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-REVIEW-004",
            kind="agent-jobs",
            message="review bundle failed schema validation",
            details={"issues": issues, "review-bundle-id": review_bundle_id},
        )
    return payload


def review_artifact_dir(project_root: Path, job_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id / "reviews"


def review_report_path(project_root: Path, job_id: str, review_id: str) -> Path:
    return review_artifact_dir(project_root, job_id) / f"review-report.{review_id}.json"


def review_bundle_path(project_root: Path, job_id: str) -> Path:
    return review_artifact_dir(project_root, job_id) / "review-bundle.json"


def persist_review_report(project_root: Path, job_id: str, payload: dict[str, Any]) -> Path:
    path = review_report_path(project_root, job_id, payload["review-id"])
    atomic_write_json(path, payload)
    return path


def persist_review_bundle(project_root: Path, job_id: str, payload: dict[str, Any]) -> Path:
    path = review_bundle_path(project_root, job_id)
    atomic_write_json(path, payload)
    return path


def read_review_bundle(project_root: Path, job_id: str) -> dict[str, Any]:
    path = review_bundle_path(project_root, job_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-REVIEW-001",
            kind="agent-jobs",
            message="failed to read review bundle",
            details={"job-id": job_id, "error": str(exc)},
        ) from exc
    issues = validate_review_bundle(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-REVIEW-005",
            kind="agent-jobs",
            message="review bundle failed validation",
            details={"job-id": job_id, "issues": issues},
        )
    return payload
