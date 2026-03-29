from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.server.service_boundary import CoreServiceBoundary
from audiagentic.jobs.store import job_record_path
from tests.helpers import sandbox as sandbox_helper


def test_service_boundary_runs_job_in_process(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "server-seam")
    try:
        request = json.loads(
            (ROOT / "docs" / "examples" / "fixtures" / "server-seam.request.json").read_text(
                encoding="utf-8"
            )
        )
        boundary = CoreServiceBoundary(sandbox.repo)
        result = boundary.run_job(request, now_fn=lambda: "2026-03-30T00:00:00Z")
        assert result["state"] == "completed"
        assert job_record_path(sandbox.repo, request["job-id"]).exists()
    finally:
        sandbox.cleanup()


def test_service_boundary_rejects_invalid_request(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "server-seam-invalid")
    try:
        boundary = CoreServiceBoundary(sandbox.repo)
        try:
            boundary.run_job({"packet-id": "pkt", "project-id": "proj"})
        except AudiaGenticError as exc:
            assert exc.kind == "validation"
        else:
            raise AssertionError("expected validation error")
        assert not job_record_path(sandbox.repo, "job_missing").exists()
    finally:
        sandbox.cleanup()


def test_service_boundary_release_status_idempotent(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "server-seam-release")
    try:
        boundary = CoreServiceBoundary(sandbox.repo)
        first = boundary.get_release_status()
        second = boundary.get_release_status()
        assert first == second
    finally:
        sandbox.cleanup()
