from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.providers.adapters import gemini


def test_gemini_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(gemini.shutil, "which", lambda _: r"C:\\Tools\\gemini.exe")

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
            stdout = "gemini completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr(gemini, "run_streaming_command", fake_run_streaming_command)

    result = gemini.run(
        {
            "provider-id": "gemini",
            "packet-id": "pkt-job-003",
            "project-id": "my-project",
            "workflow-profile": "standard",
            "working-root": tmp_path,
        },
        {"default-model": "gemini-stub", "access-mode": "cli"},
    )

    assert result["provider-id"] == "gemini"
    assert result["status"] == "ok"
    assert result["execution-mode"] == "cli"
    assert result["model"] == "gemini-stub"
    assert result["output"] == "gemini completed"
    assert captured["command"][0] == r"C:\\Tools\\gemini.exe"
    assert captured["command"][1] == "-p"
    assert str(captured["command"][2]).startswith(
        "AUDiaGentic Gemini provider execution request."
    )
    assert captured["command"][3:5] == ["-o", "text"]
    assert "--yolo" not in captured["command"]
    assert captured["cwd"] == tmp_path
    assert captured["stdout_sinks"]
    assert captured["stderr_sinks"]


def test_gemini_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(gemini.shutil, "which", lambda _: None)

    try:
        gemini.run({"provider-id": "gemini"}, {"default-model": "gemini-stub"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-005"
        assert exc.kind == "external"
    else:
        raise AssertionError("expected missing command error")
