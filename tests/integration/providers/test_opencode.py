from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.execution.providers.adapters import opencode


def test_opencode_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(opencode.shutil, "which", lambda _: r"C:\\Tools\\opencode.exe")

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

        class Result:
            returncode = 0
            stdout = "\n".join(
                [
                    '{"type":"session.started","sessionID":"sess-123"}',
                    '{"type":"assistant.message","text":"opencode completed"}',
                ]
            )
            stderr = ""

        return Result()

    monkeypatch.setattr(opencode, "run_streaming_command", fake_run_streaming_command)

    result = opencode.run(
        {
            "provider-id": "opencode",
            "job-id": "job-123",
            "packet-id": "PKT-PRV-064",
            "workflow-profile": "standard",
            "working-root": str(tmp_path),
            "prompt-body": "Reply with ok.",
        },
        {"default-model": "openai/gpt-5", "access-mode": "cli"},
    )

    assert result["provider-id"] == "opencode"
    assert result["status"] == "ok"
    assert result["session-id"] == "sess-123"
    assert result["model"] == "openai/gpt-5"
    assert result["output"] == "opencode completed"
    assert captured["command"][0] == r"C:\\Tools\\opencode.exe"
    assert captured["command"][1:4] == ["run", "--format", "json"]
    assert "--dir" not in captured["command"]
    assert "--model" in captured["command"]
    assert captured["stdout_sinks"]
    assert captured["stderr_sinks"]
    assert captured["cwd"] == tmp_path


def test_opencode_adapter_handles_empty_or_non_json_output(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(opencode.shutil, "which", lambda _: r"C:\\Tools\\opencode.exe")

    def fake_run_streaming_command(
        command,
        *,
        cwd=None,
        input_text=None,
        stdout_sinks=None,
        stderr_sinks=None,
    ):
        class Result:
            returncode = 0
            stdout = "plain text line\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(opencode, "run_streaming_command", fake_run_streaming_command)

    result = opencode.run(
        {
            "provider-id": "opencode",
            "job-id": "job-123",
            "packet-id": "PKT-PRV-064",
            "workflow-profile": "standard",
            "working-root": str(tmp_path),
            "prompt-body": "Reply with ok.",
        },
        {"default-model": "openai/gpt-5", "access-mode": "cli"},
    )

    assert result["session-id"] is None
    assert result["output"] == "plain text line"


def test_opencode_adapter_raises_on_non_zero_return(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(opencode.shutil, "which", lambda _: r"C:\\Tools\\opencode.exe")

    def fake_run_streaming_command(
        command,
        *,
        cwd=None,
        input_text=None,
        stdout_sinks=None,
        stderr_sinks=None,
    ):
        class Result:
            returncode = 2
            stdout = '{"type":"assistant.message","text":"failed"}'
            stderr = "boom"

        return Result()

    monkeypatch.setattr(opencode, "run_streaming_command", fake_run_streaming_command)

    try:
        opencode.run(
            {
                "provider-id": "opencode",
                "job-id": "job-123",
                "packet-id": "PKT-PRV-064",
                "workflow-profile": "standard",
                "working-root": str(tmp_path),
                "prompt-body": "Reply with ok.",
            },
            {"default-model": "openai/gpt-5", "access-mode": "cli"},
        )
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-012"
        assert exc.details["returncode"] == 2
        assert exc.details["provider-id"] == "opencode"
    else:
        raise AssertionError("expected AudiaGenticError")


def test_opencode_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(opencode.shutil, "which", lambda _: None)

    try:
        opencode.run({"provider-id": "opencode"}, {"default-model": "openai/gpt-5"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-011"
        assert exc.details["provider-id"] == "opencode"
    else:
        raise AssertionError("expected AudiaGenticError")
