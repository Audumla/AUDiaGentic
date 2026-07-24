"""HA04/MA35: copilot executes via its declarative execution: recipe.

The hand-written adapters/copilot/adapter.py was deleted as a byte-for-byte
duplicate of the copilot.yaml execution: block.
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

register_all_components()


def test_copilot_recipe_contract(monkeypatch, tmp_path: Path) -> None:
    execution = all_descriptors()["copilot"].execution
    assert execution is not None, "copilot must carry an execution: recipe"

    captured: dict[str, object] = {}
    monkeypatch.setattr(base_runner, "require_executable", lambda _pid, *_aliases: "/fake/gh")

    def fake_run_streaming_command(command, *, cwd=None, input_text=None, stdout_sinks=None, stderr_sinks=None):
        captured["command"] = command

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr(base_runner, "run_streaming_command", fake_run_streaming_command)

    result = make_runner_from_execution("copilot", execution)(
        {"provider-id": "copilot", "job-id": "job-test-001", "working-root": str(tmp_path)},
        {"default-model": "copilot-stub"},
    )
    assert result["provider-id"] == "copilot"
    assert result["status"] == "ok"
    assert result["returncode"] == 0
    # recipe args-template embeds the copilot suggest invocation
    assert captured["command"][:4] == ["/fake/gh", "copilot", "suggest", "-t"]
