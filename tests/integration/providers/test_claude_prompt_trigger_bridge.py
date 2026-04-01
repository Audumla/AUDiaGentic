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


def _write_claude_required_assets(sandbox) -> None:
    """Write required Claude assets to sandbox."""
    # CLAUDE.md
    (sandbox.repo / "CLAUDE.md").write_text("# CLAUDE.md\n", encoding="utf-8")

    # .claude/rules/
    (sandbox.repo / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
    (sandbox.repo / ".claude" / "rules" / "prompt-tags.md").write_text(
        "# Prompt tags\n", encoding="utf-8"
    )
    (sandbox.repo / ".claude" / "rules" / "review-policy.md").write_text(
        "# Review policy\n", encoding="utf-8"
    )

    # .claude/skills/
    skills = ["plan", "implement", "review", "audit", "check-in-prep"]
    for skill in skills:
        (sandbox.repo / ".claude" / "skills" / skill).mkdir(parents=True, exist_ok=True)
        (sandbox.repo / ".claude" / "skills" / skill / "SKILL.md").write_text(
            f"# {skill} skill\n", encoding="utf-8"
        )


def test_claude_prompt_trigger_bridge_script_launches_job(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "claude-prompt-trigger-bridge")
    try:
        _write_project_and_provider_config(sandbox)
        _write_claude_required_assets(sandbox)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "claude_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@plan target=packet:PKT-JOB-008 provider=claude model=sonnet profile=standard\n"
            "Continue implementing the packet.\n",
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "created"
        assert payload["job"]["provider-id"] == "claude"
        assert payload["job"]["launch-tag"] == "plan"
        assert payload["job"]["launch-target"]["kind"] == "packet"
        assert payload["job"]["launch-target"]["packet-id"] == "PKT-JOB-008"
    finally:
        sandbox.cleanup()


def test_claude_prompt_trigger_bridge_missing_assets_returns_validation_error(tmp_path: Path) -> None:
    """Verify that missing Claude assets trigger validation error before launch."""
    sandbox = sandbox_helper.create(tmp_path, "claude-prompt-trigger-missing-assets")
    try:
        _write_project_and_provider_config(sandbox)

        # Intentionally don't create .claude/skills directory
        # This simulates the missing assets condition

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "claude_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@plan target=packet:PKT-JOB-008\nContinue implementing.\n",
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["kind"] == "validation"
        assert "missing" in payload
        assert any("SKILL.md" in m for m in payload["missing"])
    finally:
        sandbox.cleanup()
