from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.helpers import sandbox as sandbox_helper
from audiagentic.runtime.release.fragments import record_change_event


def test_release_bootstrap_creates_install_and_release_artifacts(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "project-release-bootstrap")
    try:
        (sandbox.repo / ".audiagentic").mkdir(parents=True, exist_ok=True)
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
        record_change_event(
            sandbox.repo,
            {
                "contract-version": "v1",
                "event-id": "chg_test_self_host_001",
                "timestamp-utc": "2026-03-31T00:00:00Z",
                "project-id": "project-release-test",
                "source": {
                    "kind": "interactive-prompt",
                    "provider-id": "codex",
                    "surface": "terminal",
                    "session-id": "local",
                    "job-id": None,
                    "packet-id": "PKT-RLS-011",
                },
                "change-class": "docs",
                "files": ["docs/releases/CURRENT_RELEASE.md"],
                "diff-stats": {
                    "files-changed": 1,
                    "insertions": 1,
                    "deletions": 0,
                },
                "technical-summary": "Seeded project release bootstrap test event.",
                "user-summary-candidate": "Seeded a project release bootstrap event.",
                "status": "unreleased",
            },
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "src" / "audiagentic" / "channels" / "cli" / "main.py"),
                "release-bootstrap",
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
        assert payload["installed-state"] == "audiagentic-current"
        assert payload["synced-fragments"] == 1

        assert (sandbox.repo / ".audiagentic" / "project.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "components.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "installed.json").is_file()
        assert (sandbox.repo / ".audiagentic" / "prompt-syntax.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "prompts" / "ag-review" / "default.md").is_file()
        assert (sandbox.repo / "AGENTS.md").is_file()
        assert (sandbox.repo / ".github" / "workflows" / "release-please.audiagentic.yml").is_file()
        assert (sandbox.repo / "docs" / "releases" / "AUDIT_SUMMARY.md").is_file()
        assert (sandbox.repo / "docs" / "releases" / "CHECKIN.md").is_file()
        assert payload["baseline-sync-report"]["excluded-paths"] == [".audiagentic/runtime/**"]
        assert "codex" in (sandbox.repo / ".audiagentic" / "providers.yaml").read_text(encoding="utf-8")

        current_release = (sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE.md").read_text(
            encoding="utf-8"
        )
        assert "Seeded a project release bootstrap event." in current_release
    finally:
        sandbox.cleanup()
