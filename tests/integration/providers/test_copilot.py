from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.interoperability.protocols.streaming import provider_streaming as streaming
from audiagentic.interoperability.providers.adapters import copilot


def test_copilot_adapter_contract(monkeypatch, tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.stdin = None

        def poll(self) -> int:
            return 0

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(copilot.shutil, "which", lambda name: "/fake/gh")
    monkeypatch.setattr(streaming.subprocess, "Popen", lambda *a, **kw: FakeProcess())

    result = copilot.run(
        {
            "provider-id": "copilot",
            "job-id": "job-test-001",
            "working-root": str(tmp_path),
        },
        {"default-model": "copilot-stub"},
    )
    assert result["provider-id"] == "copilot"
    assert result["status"] == "ok"
    assert result["returncode"] == 0
