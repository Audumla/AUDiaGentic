from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.channels.cli.main import main
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
            ]
        ),
        encoding="utf-8",
    )


def test_prompt_trigger_bridge_launches_from_stdin(tmp_path: Path, capsys) -> None:
    sandbox = sandbox_helper.create(tmp_path, "prompt-trigger-bridge")
    previous_stdin = sys.stdin
    try:
        _write_project_and_provider_config(sandbox)
        sys.stdin = io.StringIO("@claude\nReview the packet for completeness.\n")

        exit_code = main(
            [
                "prompt-trigger-bridge",
                "--project-root",
                str(sandbox.repo),
                "--surface",
                "vscode",
                "--session-id",
                "sess_100",
            ]
        )

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "created"
        assert payload["job"]["provider-id"] == "claude"
        assert payload["job"]["launch-tag"] == "implement"
        assert payload["job"]["launch-target"]["kind"] == "adhoc"
        assert payload["job"]["launch-source"]["surface"] == "vscode"
        assert payload["job"]["launch-source"]["session-id"] == "sess_100"
    finally:
        sys.stdin = previous_stdin
        sandbox.cleanup()
