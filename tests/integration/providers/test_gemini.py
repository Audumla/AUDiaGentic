from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.execution.providers.adapters import gemini


def test_gemini_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(gemini.shutil, "which", lambda _: r"C:\\Tools\\gemini.exe")

    def fake_run(command, *, cwd=None, check=None, capture_output=None, text=None, encoding=None, errors=None):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["cwd"] = cwd
        captured["check"] = check
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["encoding"] = encoding
        captured["errors"] = errors

        class Completed:
            returncode = 0
            stdout = "gemini completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr(gemini.subprocess, "run", fake_run)

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
    assert str(captured["command"][2]).startswith("AUDiaGentic Gemini provider execution request.")
    assert captured["command"][3:6] == ["-o", "text", "--yolo"]
    assert captured["cwd"] == str(tmp_path)
    assert captured["check"] is False
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_gemini_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(gemini.shutil, "which", lambda _: None)

    try:
        gemini.run({"provider-id": "gemini"}, {"default-model": "gemini-stub"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-005"
        assert exc.kind == "external"
    else:
        raise AssertionError("expected missing command error")
