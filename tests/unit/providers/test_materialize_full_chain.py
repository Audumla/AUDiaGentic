"""Test full chain: providers_api -> public_materialize -> adapter install modules."""

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


def test_opencode_through_providers_api(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    providers_api.materialize_provider_config(
        project_root, "opencode", HARNESS_CFG
    )

    assert (project_root / ".opencode" / "config.json").exists()
    config_text = (project_root / ".opencode" / "config.json").read_text()
    assert "audiagentic" in config_text


def test_unknown_provider_raises(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(Exception) as exc_info:
        providers_api.materialize_provider_config(
            project_root, "unknown", HARNESS_CFG
        )

    assert "No materialize handler" in str(exc_info.value)
