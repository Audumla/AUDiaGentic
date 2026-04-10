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
                "  qwen:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: none",
                "    default-model: qwen-coder",
                "    model-aliases:",
                "      fast: qwen-coder",
                "      deep: qwen-max",
                "    catalog-refresh:",
                "      source: static",
                "      max-age-hours: 168",
            ]
        ),
        encoding="utf-8",
    )


def test_qwen_prompt_trigger_bridge_script_launches_job(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "qwen-prompt-trigger-bridge")
    try:
        _write_project_and_provider_config(sandbox)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "bridges" / "qwen_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@plan target=packet:PKT-JOB-008 provider=qwen\n"
            "Outline the next stage.\n",
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "created"
        assert payload["job"]["provider-id"] == "qwen"
        assert payload["job"]["launch-tag"] == "ag-plan"
        assert payload["job"]["launch-target"]["kind"] == "packet"
        assert payload["job"]["launch-target"]["packet-id"] == "PKT-JOB-008"
    finally:
        sandbox.cleanup()
