from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.jobs.packet_runner import run_packet
from audiagentic.jobs.store import job_record_path
from audiagentic.providers.selection import select_provider
from tests.helpers import sandbox as sandbox_helper


def _descriptor(provider_id: str) -> dict:
    return {
        "contract-version": "v1",
        "provider-id": provider_id,
        "install-mode": "external-configured",
        "supports-jobs": True,
        "supports-interactive": True,
        "supports-skill-wrapper": True,
        "supports-structured-output": True,
        "supports-server-session": False,
        "supports-baseline-healthcheck": True,
    }


def test_job_provider_seam_selects_externally(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-provider-seam")
    try:
        registry = {"local-openai": _descriptor("local-openai")}
        config = {
            "local-openai": {"enabled": True, "install-mode": "external-configured", "access-mode": "none"}
        }
        job_request = {"provider-id": "local-openai"}
        provider_id = select_provider(job_request, registry, config)

        result = run_packet(
            sandbox.repo,
            packet_id="pkt-job-010",
            project_id="my-project",
            provider_id=provider_id,
            workflow_profile="lite",
            job_id="job_20260330_0401",
            now_fn=lambda: "2026-03-30T00:00:00Z",
        )
        assert result["state"] == "completed"
        assert job_record_path(sandbox.repo, "job_20260330_0401").exists()
    finally:
        sandbox.cleanup()


def test_unhealthy_provider_blocks_job_creation(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "job-provider-unhealthy")
    try:
        registry = {"local-openai": _descriptor("local-openai")}
        config = {
            "local-openai": {"enabled": False, "install-mode": "external-configured", "access-mode": "none"}
        }
        job_request = {"provider-id": "local-openai"}
        try:
            select_provider(job_request, registry, config)
        except AudiaGenticError as exc:
            assert exc.kind == "business-rule"
        else:
            raise AssertionError("expected unhealthy provider error")
        assert not job_record_path(sandbox.repo, "job_20260330_0402").exists()
    finally:
        sandbox.cleanup()
