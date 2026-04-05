from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

from tests.helpers import sandbox as sandbox_helper


def _write_project_and_provider_config(sandbox) -> None:
    (sandbox.repo / "AGENTS.md").write_text(
        "\n".join(
            [
                "# AGENTS.md",
                "",
                "This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.",
                "",
                "## Canonical rule",
                "",
                "- Do not reinterpret `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, or `@ag-check-in-prep`.",
                "- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate workflow semantics layer.",
                "- Keep provenance visible: provider id, surface, and session id should survive normalization.",
            ]
        ),
        encoding="utf-8",
    )
    skills_root = sandbox.repo / ".agents" / "skills"
    for skill_name in ("ag-plan", "ag-implement", "ag-review", "ag-audit", "ag-check-in-prep"):
        skill_dir = skills_root / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"# {skill_name}\n\nCanonical {skill_name} skill.\n",
            encoding="utf-8",
        )
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
            ]
        ),
        encoding="utf-8",
    )
    (sandbox.repo / ".audiagentic" / "providers.yaml").write_text(
        "\n".join(
            [
                "contract-version: v1",
                "providers:",
                "  opencode:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: cli",
                "    default-model: openai/gpt-5",
            ]
        ),
        encoding="utf-8",
    )


def test_opencode_prompt_trigger_bridge_requires_assets(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "opencode-prompt-trigger-bridge-missing-assets")
    try:
        (sandbox.repo / ".audiagentic").mkdir(parents=True, exist_ok=True)
        (sandbox.repo / ".audiagentic" / "project.yaml").write_text("contract-version: v1\nproject-id: sample-project\nproject-name: Sample Project\nworkflow-profile: standard\ntracked-docs-root: docs\nruntime-root: .audiagentic/runtime\nrelease-strategy: release-please\nprompt-launch:\n  syntax: prefix-token-v1\n  allow-adhoc-target: false\n", encoding="utf-8")
        (sandbox.repo / ".audiagentic" / "providers.yaml").write_text("contract-version: v1\nproviders:\n  opencode:\n    enabled: true\n    install-mode: external-configured\n    access-mode: cli\n    default-model: openai/gpt-5\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "opencode_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@ag-implement provider=opencode\nContinue implementing the packet.\n",
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["kind"] == "validation"
        assert "AGENTS.md" in payload["missing"]
    finally:
        sandbox.cleanup()


def test_opencode_prompt_trigger_bridge_launches_job(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "opencode-prompt-trigger-bridge")
    try:
        _write_project_and_provider_config(sandbox)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "opencode_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@ag-implement target=packet:PKT-PRV-064 provider=opencode\nContinue implementing the packet.\n",
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "created"
        assert payload["job"]["provider-id"] == "opencode"
        assert payload["job"]["launch-tag"] == "ag-implement"
        assert payload["job"]["launch-target"]["kind"] == "packet"
        assert payload["job"]["launch-target"]["packet-id"] == "PKT-PRV-064"
    finally:
        sandbox.cleanup()
