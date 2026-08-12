"""Test full chain: providers_api -> public_materialize -> adapter install modules."""

import json
from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api

HARNESS_CFG = {
    "rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"},
}


def test_pi_through_providers_api(tmp_path: Path):
    project_root = tmp_path / "project"
    agent_runtime = tmp_path / "harness"
    project_root.mkdir()
    agent_runtime.mkdir()

    providers_api.materialize_provider_config(
        project_root, "pi", HARNESS_CFG, agent_runtime=agent_runtime
    )

    assert (agent_runtime / "agent" / "models.json").exists()
    assert (agent_runtime / "agent" / "settings.json").exists()
    models_text = (agent_runtime / "agent" / "models.json").read_text()
    assert "audiagentic" in models_text


def test_opencode_through_providers_api_preserves_user_model_config(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / ".opencode" / "opencode.json"
    config_path.parent.mkdir()
    user_config = {
        "$schema": "https://opencode.ai/config.json",
        "theme": "my-custom-theme",
        "agent": {"reviewer": {"mode": "subagent"}},
        "mcp": {"user-mcp": {"type": "local", "command": ["user-server"]}},
        "plugin": ["@user/opencode-plugin"],
        "lsp": {"python": {"command": ["user-pyright"], "extensions": [".py"]}},
        "provider": {
            "custom": {
                "options": {"baseURL": "https://models.example.test/v1"},
                "models": {"my-model": {"name": "My model"}},
            }
        },
    }
    config_path.write_text(json.dumps(user_config), encoding="utf-8")

    providers_api.materialize_provider_config(
        project_root, "opencode", HARNESS_CFG
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["theme"] == user_config["theme"]
    assert config["agent"] == user_config["agent"]
    assert config["mcp"] == user_config["mcp"]
    assert config["plugin"] == user_config["plugin"]
    assert config["lsp"] == user_config["lsp"]
    assert config["provider"]["custom"] == user_config["provider"]["custom"]
    assert "audiagentic" in config["provider"]
    assert "qwen3.5-0.8b" in config["provider"]["audiagentic"]["models"]
    assert (project_root / ".opencode" / "audiagentic-models.json").exists()
    assert not (project_root / ".opencode" / "config.json").exists()


def test_unknown_provider_raises(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(Exception) as exc_info:
        providers_api.materialize_provider_config(
            project_root, "unknown", HARNESS_CFG
        )

    assert "does not declare config materialization" in str(exc_info.value)
