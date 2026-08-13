from __future__ import annotations

# These integration tests bootstrap the repository and source roots before
# importing the application under test.
# ruff: noqa: E402, I001

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.components.agent_jobs.prompt_launch import launch_prompt_request
from audiagentic.components.agent_jobs.prompt_parser import parse_prompt_launch_request
from tests.helpers import sandbox as sandbox_helper


def _write_project_and_provider_config(sandbox) -> None:
    (sandbox.repo / ".audiagentic").mkdir(parents=True, exist_ok=True)
    (sandbox.repo / ".audiagentic" / "config").mkdir(parents=True, exist_ok=True)
    (sandbox.repo / ".audiagentic" / "config" / "project.yaml").write_text(
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
    (sandbox.repo / ".audiagentic" / "config" / "runtime").mkdir(parents=True, exist_ok=True)
    (sandbox.repo / ".audiagentic" / "config" / "runtime" / "providers.yaml").write_text(
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


def test_prompt_launch_submits_canonical_work(tmp_path: Path, monkeypatch) -> None:
    sandbox = sandbox_helper.create(tmp_path, "prompt-launch")
    try:
        _write_project_and_provider_config(sandbox)
        request = parse_prompt_launch_request(
            "@adhoc target=packet:PKT-JOB-008 provider=codex model=gpt-5.4-mini profile=standard\n"
            "Continue implementing the packet.\n",
            surface="vscode",
            provider_id="codex",
            session_id="sess_001",
            workflow_profile="standard",
            prompt_id="prm_20260330_0001",
        )
        request["context-id"] = "ctx_prompt_launch"
        monkeypatch.setattr(
            "audiagentic.components.agents.gateway.client.get_gateway_client",
            lambda _root: _Gateway(),
        )
        result = launch_prompt_request(sandbox.repo, request)
        assert result["status"] == "submitted"
        assert result["context-id"] == "ctx_prompt_launch"
        assert not (sandbox.repo / ".audiagentic" / "runtime" / "jobs").exists()
    finally:
        sandbox.cleanup()


def test_prompt_launch_defaults_model_from_provider_shorthand(tmp_path: Path, monkeypatch) -> None:
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
        request["context-id"] = "ctx_prompt_launch_defaults"
        monkeypatch.setattr(
            "audiagentic.components.agents.gateway.client.get_gateway_client",
            lambda _root: _Gateway(),
        )
        result = launch_prompt_request(sandbox.repo, request)
        assert result["status"] == "submitted"
        assert result["context-id"] == "ctx_prompt_launch_defaults"
    finally:
        sandbox.cleanup()


class _Gateway:
    def submit_agent_work(self, root, context_id, message, **kwargs):
        return {
            "work_id": kwargs["work_id"],
            "context_id": context_id,
            "state": "active",
            "message": message,
        }
