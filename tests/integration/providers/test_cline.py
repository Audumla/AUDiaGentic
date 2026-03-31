from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.providers.adapters import cline


def test_cline_adapter_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(cline.shutil, "which", lambda _: r"C:\\Tools\\cline.exe")

    def fake_run_streaming_command(
        command,
        *,
        cwd=None,
        stdout_log_path=None,
        stderr_log_path=None,
        tee_console=False,
        input_text=None,
    ):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["stdout_log_path"] = stdout_log_path
        captured["stderr_log_path"] = stderr_log_path
        captured["tee_console"] = tee_console

        class Result:
            returncode = 0
            stdout = "\n".join(
                [
                    '{"type":"task_started","taskId":"task-123"}',
                    '{"type":"say","say":"text","text":"working"}',
                    '{"type":"completion_result","text":"cline completed"}',
                ]
            )
            stderr = ""

        return Result()

    monkeypatch.setattr(cline, "run_streaming_command", fake_run_streaming_command)

    result = cline.run(
        {
            "provider-id": "cline",
            "job-id": "job-123",
            "packet-id": "PKT-PRV-028",
            "workflow-profile": "standard",
            "working-root": str(tmp_path),
            "prompt-body": "Reply with ok.",
        },
        {"default-model": "cline-model", "access-mode": "cli"},
    )

    assert result["provider-id"] == "cline"
    assert result["status"] == "ok"
    assert result["task-id"] == "task-123"
    assert result["model"] == "cline-model"
    assert result["output"] == "cline completed"
    assert captured["command"][0] == r"C:\\Tools\\cline.exe"
    assert "--json" in captured["command"]
    assert "--auto-approve-all" in captured["command"]
    assert "--cwd" in captured["command"]
    assert str(captured["cwd"]) == str(tmp_path)
    assert captured["tee_console"] is False
    assert str(captured["command"][-1]).startswith("AUDiaGentic Cline provider execution request.")


def test_cline_adapter_requires_command(monkeypatch) -> None:
    monkeypatch.setattr(cline.shutil, "which", lambda _: None)

    try:
        cline.run({"provider-id": "cline"}, {"default-model": "cline-model"})
    except AudiaGenticError as exc:
        assert exc.code == "PRV-EXTERNAL-009"
        assert exc.details["provider-id"] == "cline"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected AudiaGenticError")
