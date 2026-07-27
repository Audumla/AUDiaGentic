"""Test public_materialize dispatch service."""

from pathlib import Path

import pytest

from audiagentic.components.providers.services.public_materialize import (
    materialize_provider_config,
)

HARNESS_CFG = {
    "rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"},
}


def test_dispatch_to_pi(tmp_path: Path):
    project_root = tmp_path / "project"
    agent_runtime = tmp_path / "harness"
    project_root.mkdir()
    agent_runtime.mkdir()

    materialize_provider_config(project_root, "pi", HARNESS_CFG, agent_runtime=agent_runtime)

    assert (agent_runtime / "agent" / "models.json").exists()
    assert (agent_runtime / "agent" / "settings.json").exists()
    assert "audiagentic" in (agent_runtime / "agent" / "models.json").read_text()


def test_dispatch_to_opencode(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    materialize_provider_config(project_root, "opencode", HARNESS_CFG)

    assert (project_root / ".opencode" / "config.json").exists()
    assert "audiagentic" in (project_root / ".opencode" / "config.json").read_text()


def test_unknown_provider_raises(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(Exception) as exc_info:
        materialize_provider_config(project_root, "unknown", HARNESS_CFG)

    assert "No materialize handler" in str(exc_info.value)
