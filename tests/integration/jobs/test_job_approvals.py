from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.helpers import sandbox as sandbox_helper

from audiagentic.execution.jobs.approvals import (
    build_approval_request,
    check_job_approval,
    request_approval,
    request_job_approval,
)
from audiagentic.execution.jobs.records import build_job_record
from audiagentic.execution.jobs.reviews import build_review_bundle, persist_review_bundle
from audiagentic.runtime.state.jobs_store import read_job_record, write_job_record


def test_job_approval_expiration_moves_job_to_cancelled(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-approval-expire")
    try:
        job = build_job_record(
            job_id="job_20260330_0101",
            packet_id="pkt-job-005",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            state="running",
            created_at="2026-03-30T00:00:00Z",
            updated_at="2026-03-30T00:00:00Z",
        )
        write_job_record(sandbox.repo, job)
        approval = request_job_approval(
            sandbox.repo,
            job_id=job["job-id"],
            project_id="my-project",
            kind="job-continue",
            summary="Continue job",
            approval_id="apr_001",
            now_ts="2026-03-30T00:00:00Z",
        )
        assert approval["state"] == "pending"
        awaiting = read_job_record(sandbox.repo, job["job-id"])
        assert awaiting["state"] == "awaiting-approval"

        future = datetime(2026, 3, 30, 9, 0, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        approval = check_job_approval(
            sandbox.repo,
            job_id=job["job-id"],
            approval_id="apr_001",
            now_ts=future,
        )
        assert approval["state"] == "expired"
        cancelled = read_job_record(sandbox.repo, job["job-id"])
        assert cancelled["state"] == "cancelled"
    finally:
        sandbox.cleanup()


def test_duplicate_pending_approval_returns_existing(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-approval-duplicate")
    try:
        requested_at = datetime(2026, 3, 30, 0, 0, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        expires_at = (datetime(2026, 3, 30, 0, 0, 0, tzinfo=timezone.utc) + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        )
        first = build_approval_request(
            approval_id="apr_010",
            project_id="my-project",
            kind="job-continue",
            source_kind="job-service",
            source_id="job_20260330_0201",
            summary="Continue job",
            requested_at=requested_at,
            expires_at=expires_at,
        )
        stored = request_approval(sandbox.repo, first)
        second = build_approval_request(
            approval_id="apr_011",
            project_id="my-project",
            kind="job-continue",
            source_kind="job-service",
            source_id="job_20260330_0201",
            summary="Continue job",
            requested_at=requested_at,
            expires_at=expires_at,
        )
        duplicate = request_approval(sandbox.repo, second)
        assert duplicate["approval-id"] == stored["approval-id"]
    finally:
        sandbox.cleanup()


def test_review_bundle_blocks_approval_until_approved(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-approval-review-gate")
    try:
        job = build_job_record(
            job_id="job_20260330_0102",
            packet_id="pkt-job-005",
            project_id="my-project",
            provider_id="local-openai",
            workflow_profile="lite",
            state="running",
            created_at="2026-03-30T00:00:00Z",
            updated_at="2026-03-30T00:00:00Z",
            review_bundle_id="rvb_20260330_0102",
        )
        write_job_record(sandbox.repo, job)
        bundle = build_review_bundle(
            review_bundle_id="rvb_20260330_0102",
            subject={"kind": "job", "job-id": job["job-id"]},
            required_reviews=1,
            aggregation_rule="all-pass",
            require_distinct_reviewers=True,
            reports=[
                {"review-id": "rvr_1", "reviewer-key": "claude:cli:sess_1", "recommendation": "rework"}
            ],
        )
        persist_review_bundle(sandbox.repo, job["job-id"], bundle)
        try:
            request_job_approval(
                sandbox.repo,
                job_id=job["job-id"],
                project_id="my-project",
                kind="job-continue",
                summary="Continue job",
                approval_id="apr_002",
                now_ts="2026-03-30T00:00:00Z",
            )
        except Exception as exc:  # noqa: BLE001
            assert "review bundle is not approved" in str(exc)
        else:
            raise AssertionError("expected review gate failure")
    finally:
        sandbox.cleanup()
