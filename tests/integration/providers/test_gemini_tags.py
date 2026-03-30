from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.adapters import gemini
from tests.helpers import sandbox as sandbox_helper

def test_gemini_adapter_recognizes_tag(monkeypatch, tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "gemini-tag")
    try:
        # Write project config
        (sandbox.repo / ".audiagentic").mkdir(parents=True, exist_ok=True)
        (sandbox.repo / ".audiagentic" / "project.yaml").write_text(
            "project-id: test-project\nprompt-launch:\n  allow-adhoc-target: true\n",
            encoding="utf-8"
        )

        captured: dict[str, object] = {}
        monkeypatch.setattr(gemini.shutil, "which", lambda _: "gemini")

        def fake_run(command, **kwargs):
            captured["command"] = command
            class Completed:
                returncode = 0
                stdout = "gemini processed plan"
                stderr = ""
            return Completed()

        monkeypatch.setattr(gemini.subprocess, "run", fake_run)

        # Run with a tagged prompt
        packet_ctx = {
            "provider-id": "gemini",
            "prompt-body": "@plan target=packet:PKT-001\nDo the work.",
            "working-root": str(sandbox.repo),
            "project-id": "test-project",
            "workflow-profile": "standard",
            "surface": "cli"
        }
        provider_cfg = {"default-model": "gemini-1.5", "access-mode": "cli"}

        result = gemini.run(packet_ctx, provider_cfg)

        assert result["status"] == "ok"
        # Check the normalized execution prompt reaches gemini
        assert "AUDiaGentic Gemini provider execution request." in captured["command"][2]
        assert "Do the work." in captured["command"][2]
    finally:
        sandbox.cleanup()

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))
