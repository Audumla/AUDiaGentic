from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.execution.providers.adapters import claude


def test_claude_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(claude.shutil, "which", lambda _: r"C:\\Tools\\claude.exe")

    def fake_run(command, *, cwd=None, check=None, capture_output=None, text=None, encoding=None, errors=None, input=None):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["cwd"] = cwd
        captured["check"] = check
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["encoding"] = encoding
        captured["errors"] = errors
        captured["input"] = input

        class Completed:
            returncode = 0
            stdout = "claude completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr(claude.subprocess, "run", fake_run)

    result = claude.run(
        {
            "provider-id": "claude",
            "packet-id": "pkt-job-003",
            "project-id": "my-project",
            "workflow-profile": "standard",
            "working-root": tmp_path,
        },
        {"default-model": "claude-stub", "access-mode": "cli"},
    )

    assert result["provider-id"] == "claude"
    assert result["status"] == "ok"
    assert result["execution-mode"] == "cli"
    assert result["model"] == "claude-stub"
    assert result["output"] == "claude completed"
    assert captured["command"][0] == r"C:\\Tools\\claude.exe"
    assert captured["command"][1:4] == ["--print", "--output-format", "text"]
    assert captured["input"].startswith("AUDiaGentic Claude provider execution request.")
    assert captured["cwd"] == str(tmp_path)
    assert captured["check"] is False
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_claude_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda _: None)

    try:
        claude.run({"provider-id": "claude"}, {"default-model": "claude-stub"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-003"
        assert exc.kind == "external"
    else:
        raise AssertionError("expected missing command error")
