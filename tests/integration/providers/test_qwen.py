"""HA04/MA35: qwen executes via its declarative execution: recipe.

The hand-written adapters/qwen/adapter.py was deleted as a byte-for-byte
duplicate of the qwen.yaml execution: block. This drives the generic recipe
runner (make_runner_from_execution) that now serves qwen.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

import audiagentic.components.providers.adapters.base_runner as base_runner
from audiagentic.components.providers.adapters.base_runner import make_runner_from_execution
from audiagentic.components.providers.descriptors.registry import all_descriptors
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.contracts.errors import AudiaGenticError

register_all_components()


def _qwen_runner():
    execution = all_descriptors()["qwen"].execution
    assert execution is not None, "qwen must carry an execution: recipe"
    return make_runner_from_execution("qwen", execution)


def test_qwen_recipe_executes_cli(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(base_runner, "require_executable", lambda _pid, *_aliases: r"C:\Tools\qwen.exe")

    def fake_run_streaming_command(command, *, cwd=None, input_text=None, stdout_sinks=None, stderr_sinks=None):
        captured["command"] = command
        captured["cwd"] = cwd

        class Completed:
            returncode = 0
            stdout = "qwen completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr(base_runner, "run_streaming_command", fake_run_streaming_command)

    result = _qwen_runner()(
        {
            "provider-id": "qwen",
            "packet-id": "pkt-job-003",
            "workflow-profile": "standard",
            "working-root": str(tmp_path),
        },
        {"default-model": "qwen-coder", "access-mode": "cli"},
    )

    assert result["provider-id"] == "qwen"
    assert result["status"] == "ok"
    assert result["output"] == "qwen completed"
    command = captured["command"]
    assert command[0] == r"C:\Tools\qwen.exe"
    # recipe args-template: [{approval-flags}, {model-flags}, {prompt}]
    assert "-m" in command and "qwen-coder" in command
    assert command[-1].startswith("AUDiaGentic Qwen provider execution request.")


def test_qwen_recipe_requires_cli(monkeypatch, tmp_path: Path) -> None:
    def _raise(_pid, *_aliases):
        raise AudiaGenticError(code="EXT-PROVCLI-001", kind="providers", message="missing")

    monkeypatch.setattr(base_runner, "require_executable", _raise)
    try:
        _qwen_runner()({"provider-id": "qwen"}, {"default-model": "qwen-coder"})
    except AudiaGenticError as exc:
        assert exc.code == "EXT-PROVCLI-001"
    else:
        raise AssertionError("expected missing-CLI error")
