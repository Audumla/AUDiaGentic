from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.interoperability.providers.adapters import codex
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_codex_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(codex.shutil, "which", lambda _: r"C:\\Tools\\codex.exe")

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
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("codex completed", encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = "codex stdout"
            stderr = ""

        return Completed()

    monkeypatch.setattr(codex, "run_streaming_command", fake_run_streaming_command)

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
    assert captured["command"][1] == "exec"
    assert "--ephemeral" in captured["command"]
    assert "--skip-git-repo-check" in captured["command"]
    assert "--full-auto" in captured["command"]
    assert captured["command"][-1].startswith(
        "AUDiaGentic Codex provider execution request."
    )
    assert captured["cwd"] == tmp_path
    assert captured["stdout_sinks"]
    assert captured["stderr_sinks"]


def test_codex_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda _: None)

    try:
        codex.run({"provider-id": "codex"}, {"default-model": "codex-stub"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-001"
        assert exc.kind == "external"
    else:
        raise AssertionError("expected missing command error")
