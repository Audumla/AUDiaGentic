from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

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
            ]
        ),
        encoding="utf-8",
    )
    (sandbox.repo / ".audiagentic" / "providers.yaml").write_text(
        "\n".join(
            [
                "contract-version: v1",
                "providers:",
                "  gemini:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: cli",
                "    default-model: gemini-2.5-flash",
                "    model-aliases:",
                "      fast: gemini-2.5-flash",
                "      deep: gemini-2.5-pro",
                "    catalog-refresh:",
                "      source: cli",
                "      max-age-hours: 168",
            ]
        ),
        encoding="utf-8",
    )


def test_gemini_prompt_trigger_bridge_script_launches_job(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "gemini-prompt-trigger-bridge")
    try:
        _write_project_and_provider_config(sandbox)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "gemini_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@review target=artifact:art_job_0007_impl_plan provider=gemini\n"
            "Review the artifact for completeness.\n",
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "open"
        assert payload["review-bundle-id"].startswith("rvb_")
    finally:
        sandbox.cleanup()
