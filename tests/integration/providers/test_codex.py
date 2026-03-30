from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.adapters import codex
from audiagentic.contracts.errors import AudiaGenticError


def test_codex_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(codex.shutil, "which", lambda _: r"C:\\Tools\\codex.exe")

    def fake_run(command, *, cwd=None, check=None, capture_output=None, text=None, encoding=None, errors=None):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["cwd"] = cwd
        captured["check"] = check
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["encoding"] = encoding
        captured["errors"] = errors
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("codex completed", encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = "codex stdout"
            stderr = ""

        return Completed()

    monkeypatch.setattr(codex.subprocess, "run", fake_run)

    result = codex.run(
        {
            "provider-id": "codex",
            "packet-id": "pkt-job-003",
            "project-id": "my-project",
            "workflow-profile": "standard",
            "working-root": tmp_path,
        },
        {"default-model": "gpt-5.4-mini", "access-mode": "cli"},
    )

    assert result["provider-id"] == "codex"
    assert result["status"] == "ok"
    assert result["execution-mode"] == "cli"
    assert result["model"] == "gpt-5.4-mini"
    assert result["output"] == "codex completed"
    assert captured["command"][0] == r"C:\\Tools\\codex.exe"
    assert captured["command"][1:4] == ["exec", "--ephemeral", "--skip-git-repo-check"]
    assert captured["command"][-1].startswith("AUDiaGentic Codex provider execution request.")
    assert captured["cwd"] == str(tmp_path)
    assert captured["check"] is False
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_codex_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda _: None)

    try:
        codex.run({"provider-id": "codex"}, {"default-model": "codex-stub"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-001"
        assert exc.kind == "external"
    else:
        raise AssertionError("expected missing command error")
