from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.execution.jobs.prompt_launch import launch_prompt_request
from audiagentic.execution.jobs import prompt_launch
from audiagentic.execution.jobs.prompt_parser import parse_prompt_launch_request
from audiagentic.runtime.state.jobs_store import job_record_path
from tests.helpers import sandbox as sandbox_helper


def _write_project_and_provider_config(sandbox) -> None:
    (sandbox.repo / ".audiagentic").mkdir(parents=True, exist_ok=True)
    (sandbox.repo / ".audiagentic" / "project.yaml").write_text(
        "\n".join(
            [
                "contract-version: v1",
                "project-id: sample-project",
                "project-name: Sample Project",
                "workflow-profile: standard",
                "tracked-docs-root: docs",
                "runtime-root: .audiagentic/runtime",
                "release-strategy: release-please",
                "prompt-launch:",
                "  syntax: prefix-token-v1",
                "  allow-adhoc-target: false",
                "  default-review-policy:",
                "    required-reviews: 2",
                "    aggregation-rule: all-pass",
                "    require-distinct-reviewers: true",
                "  default-stream-controls:",
                "    enabled: true",
                "    tee-console: true",
                "    capture-stdout: true",
                "    capture-stderr: true",
                "    capture-progress: true",
                "    event-format: ndjson",
                "  default-input-controls:",
                "    enabled: true",
                "    tee-console: true",
                "    capture-stdin: true",
                "    capture-input-events: true",
                "    allow-pause-resume: true",
                "    event-format: ndjson",
            ]
        ),
        encoding="utf-8",
    )
    (sandbox.repo / ".audiagentic" / "providers.yaml").write_text(
        "\n".join(
            [
                "contract-version: v1",
                "providers:",
                "  codex:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: cli",
                "    default-model: gpt-5.4-mini",
                "    model-aliases:",
                "      fast: gpt-5.4-mini",
                "      deep: gpt-5.4",
                "    catalog-refresh:",
                "      source: cli",
                "      max-age-hours: 168",
                "  claude:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: cli",
                "    default-model: sonnet",
                "    model-aliases:",
                "      fast: sonnet",
                "      deep: opus",
                "    catalog-refresh:",
                "      source: cli",
                "      max-age-hours: 168",
                "  cline:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: cli",
                "    default-model: gpt-5.4-mini",
                "    model-aliases:",
                "      fast: gpt-5.4-mini",
                "      deep: gpt-5.4",
                "    catalog-refresh:",
                "      source: cli",
                "      max-age-hours: 168",
            ]
        ),
        encoding="utf-8",
    )


def test_prompt_launch_creates_job_and_launch_artifact(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "prompt-launch")
    try:
        _write_project_and_provider_config(sandbox)
        request = parse_prompt_launch_request(
            "@plan target=packet:PKT-JOB-008 provider=codex model=gpt-5.4-mini profile=standard\n"
            "Continue implementing the packet.\n",
            surface="vscode",
            provider_id="codex",
            session_id="sess_001",
            workflow_profile="standard",
            prompt_id="prm_20260330_0001",
        )
        result = launch_prompt_request(sandbox.repo, request)
        assert result["status"] == "created"
        job = result["job"]
        assert job["launch-tag"] == "ag-plan"
        assert job["model-id"] == "gpt-5.4-mini"
        assert job_record_path(sandbox.repo, job["job-id"]).exists()
        launch_path = sandbox.repo / ".audiagentic" / "runtime" / "jobs" / job["job-id"] / "launch-request.json"
        assert json.loads(launch_path.read_text(encoding="utf-8"))["prompt-id"] == "prm_20260330_0001"
    finally:
        sandbox.cleanup()


def test_prompt_launch_defaults_model_and_job_subject_from_provider_shorthand(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "prompt-launch-defaults")
    try:
        _write_project_and_provider_config(sandbox)
        request = parse_prompt_launch_request(
            "@codex\nShip the next safe increment.\n",
            surface="cli",
            provider_id=None,
            session_id="sess_010",
            workflow_profile="standard",
            prompt_id="prm_20260330_0010",
        )
        result = launch_prompt_request(sandbox.repo, request)
        assert result["status"] == "created"
        job = result["job"]
        assert job["provider-id"] == "codex"
        assert job["model-id"] == "gpt-5.4-mini"
        assert job["default-model"] == "gpt-5.4-mini"
        assert job["launch-target"]["kind"] == "adhoc"
        assert job["launch-target"]["adhoc-id"] == "adh_20260330_0010"
        assert job["job-id"].startswith("job_")
    finally:
        sandbox.cleanup()


def test_prompt_review_creates_review_artifacts(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "prompt-review")
    original_execute_provider = prompt_launch.execute_provider
    try:
        _write_project_and_provider_config(sandbox)
        captured: dict[str, object] = {}

        def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):  # type: ignore[no-untyped-def]
            captured["packet_ctx"] = packet_ctx
            return {
                "provider-id": provider_id,
                "status": "ok",
                "output": json.dumps(
                    {
                        "findings": [
                            {
                                "finding-id": "fdg_001",
                                "severity": "minor",
                                "blocking": False,
                                "summary": "Template-driven review executed.",
                                "suggested-fix": "None needed.",
                            }
                        ],
                        "recommendation": "pass-with-notes",
                        "follow-up-actions": ["Archive the review output."],
                    }
                ),
            }

        original_execute_provider = prompt_launch.execute_provider
        prompt_launch.execute_provider = fake_execute_provider  # type: ignore[assignment]
        request = parse_prompt_launch_request(
            "@r-cline id=job_001 ctx=documentation t=review-default\n",
            surface="cli",
            provider_id="cline",
            session_id="sess_044",
            workflow_profile="standard",
            prompt_id="prm_20260330_0044",
            project_root=sandbox.repo,
        )
        result = launch_prompt_request(sandbox.repo, request)
        assert result["status"] == "open"
        review_root = sandbox.repo / ".audiagentic" / "runtime" / "jobs" / result["job-id"] / "reviews"
        assert any(review_root.glob("review-report.*.json"))
        assert (review_root / "review-bundle.json").exists()
        report = json.loads(next(review_root.glob("review-report.*.json")).read_text(encoding="utf-8"))
        assert report["recommendation"] == "pass-with-notes"
        assert report["findings"][0]["summary"] == "Template-driven review executed."
        assert report["subject"]["job-id"] == "job_001"
        assert report["criteria"]
        packet_ctx = captured["packet_ctx"]
        assert isinstance(packet_ctx, dict)
        assert packet_ctx["stream-controls"]["enabled"] is True
        assert packet_ctx["input-controls"]["capture-stdin"] is True
    finally:
        prompt_launch.execute_provider = original_execute_provider  # type: ignore[assignment]
        sandbox.cleanup()
