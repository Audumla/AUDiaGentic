from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.execution.providers.adapters import qwen


def test_qwen_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(qwen.shutil, "which", lambda _: r"C:\\Tools\\qwen.exe")

    def fake_run_streaming_command(
        command,
        *,
        cwd=None,
        input_text=None,
        stdout_sinks=None,
        stderr_sinks=None,
    ):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["stdout_sinks"] = stdout_sinks
        captured["stderr_sinks"] = stderr_sinks

        class Completed:
            returncode = 0
            stdout = "qwen completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr(qwen, "run_streaming_command", fake_run_streaming_command)

    result = qwen.run(
        {
            "provider-id": "qwen",
            "packet-id": "pkt-job-003",
            "project-id": "my-project",
            "workflow-profile": "standard",
            "working-root": tmp_path,
        },
        {"default-model": "qwen-coder", "access-mode": "cli"},
    )

    assert result["provider-id"] == "qwen"
    assert result["status"] == "ok"
    assert result["execution-mode"] == "cli"
    assert result["model"] == "qwen-coder"
    assert result["output"] == "qwen completed"
    assert captured["command"][0] == r"C:\\Tools\\qwen.exe"
    # New format: qwen [-m model] prompt (positional argument)
    assert "-m" in captured["command"]
    assert "qwen-coder" in captured["command"]
    # Prompt should be the last argument
    assert captured["command"][-1].startswith(
        "AUDiaGentic Qwen provider execution request."
    )
    assert captured["cwd"] == tmp_path
    assert captured["stdout_sinks"]
    assert captured["stderr_sinks"]


def test_qwen_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(qwen.shutil, "which", lambda _: None)

    try:
        qwen.run({"provider-id": "qwen"}, {"default-model": "qwen-coder"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-007"
        assert exc.kind == "external"
    else:
        raise AssertionError("expected missing command error")
