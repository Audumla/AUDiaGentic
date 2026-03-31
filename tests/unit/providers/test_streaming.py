from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers import streaming


def test_run_streaming_command_captures_stdout_and_stderr(monkeypatch, tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("stdout-one\nstdout-two\n")
            self.stderr = io.StringIO("stderr-one\n")
            self.stdin = None

        def wait(self) -> int:
            return 0

    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(streaming.subprocess, "Popen", fake_popen)

    result = streaming.run_streaming_command(
        ["tool", "--flag"],
        cwd=tmp_path,
        stdout_log_path=tmp_path / "stdout.log",
        stderr_log_path=tmp_path / "stderr.log",
        tee_console=False,
    )

    assert result.returncode == 0
    assert result.stdout == "stdout-one\nstdout-two\n"
    assert result.stderr == "stderr-one\n"
    assert captured["command"] == ["tool", "--flag"]
    assert captured["kwargs"]["cwd"] == str(tmp_path)
