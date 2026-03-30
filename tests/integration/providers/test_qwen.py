from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.providers.adapters import qwen


def test_qwen_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(qwen.shutil, "which", lambda _: r"C:\\Tools\\qwen.exe")

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
            stdout = "qwen completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr(qwen.subprocess, "run", fake_run)

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
    assert captured["command"][1:4] == ["-p", captured["command"][2], "-o"]
    assert str(captured["command"][2]).startswith("AUDiaGentic Qwen provider execution request.")
    assert captured["cwd"] == str(tmp_path)
    assert captured["check"] is False
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_qwen_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(qwen.shutil, "which", lambda _: None)

    try:
        qwen.run({"provider-id": "qwen"}, {"default-model": "qwen-coder"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-007"
        assert exc.kind == "external"
    else:
        raise AssertionError("expected missing command error")
