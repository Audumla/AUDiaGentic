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
                "- Do not reinterpret `@plan`, `@implement`, `@review`, `@audit`, or `@check-in-prep`.",
                "- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate workflow semantics layer.",
                "- Keep provenance visible: provider id, surface, and session id should survive normalization.",
            ]
        ),
        encoding="utf-8",
    )
    skills_root = sandbox.repo / ".agents" / "skills"
    for skill_name in ("plan", "implement", "review", "audit", "check-in-prep"):
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
            ]
        ),
        encoding="utf-8",
    )


def test_codex_prompt_trigger_bridge_requires_codex_assets(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "codex-prompt-trigger-bridge-missing-assets")
    try:
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
                    "  codex:",
                    "    enabled: true",
                    "    install-mode: external-configured",
                    "    access-mode: cli",
                    "    default-model: gpt-5.4-mini",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "codex_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@implement provider=codex\nContinue implementing the packet.\n",
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


def test_codex_prompt_trigger_bridge_script_launches_job(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "codex-prompt-trigger-bridge")
    try:
        _write_project_and_provider_config(sandbox)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "codex_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@implement target=packet:PKT-JOB-008 provider=codex model=gpt-5.4-mini\n"
            "Continue implementing the packet.\n",
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "created"
        assert payload["job"]["provider-id"] == "codex"
        assert payload["job"]["launch-tag"] == "implement"
        assert payload["job"]["launch-target"]["kind"] == "packet"
        assert payload["job"]["launch-target"]["packet-id"] == "PKT-JOB-008"
    finally:
        sandbox.cleanup()
