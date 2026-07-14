import json
from pathlib import Path

from audiagentic.components.providers.adapters.opencode.acp import build_acp_launch


def test_opencode_binding_only_declares_launch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.opencode.acp.require_executable",
        lambda *_args: "opencode",
    )
    launch = build_acp_launch(tmp_path, model_id="brutus/deep-coder")
    assert launch.executable == "opencode"
    assert launch.args == ("acp", "--cwd", str(tmp_path.resolve()))
    assert json.loads(launch.environment["OPENCODE_CONFIG_CONTENT"]) == {
        "model": "brutus/deep-coder"
    }
