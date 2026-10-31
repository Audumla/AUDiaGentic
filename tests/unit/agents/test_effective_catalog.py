"""CFG09 part 1: the hosted catalog includes compiled machine-scope agent files."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.effective_catalog import (
    EffectiveAgentsRepository,
    effective_catalog_mapping,
)
from audiagentic.components.agents.configuration.global_catalog import read_global_agents_config
from audiagentic.components.agents.configuration.repository import AgentsConfigValidationError
from audiagentic.components.agents.configuration.resolution import resolve_agent_composition
from audiagentic.components.agents.gateway.profiles import load_gateway_registry_from_agents_catalog

LEGACY = """contract-version: v2
prompts:
  main:
    content:
      - kind: text
        text: "{prompt-body}"
roles:
  reader:
    instructions: Read
execution_profiles:
  legacy-profile:
    provider_id: codex
    instances: [model-a]
agents:
  legacy-agent:
    name: Legacy
    prompt_id: main
    role_ids: [reader]
    execution_profile_id: legacy-profile
  shared:
    name: Legacy shared
    prompt_id: main
    role_ids: [reader]
    execution_profile_id: legacy-profile
"""


@pytest.fixture
def scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    return {"user_agents": tmp_path / "xdg" / "audiagentic" / "agents", "project": root, "legacy": global_agents_config_path()}


def _agent(directory: Path, name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.yaml").write_text(text, encoding="utf-8")


GPT = "schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: chatgpt\n"


def test_legacy_only_is_unchanged(scopes: dict[str, Path]) -> None:
    scopes["legacy"].write_text(LEGACY, encoding="utf-8")
    ids = [agent["agent_id"] for agent in read_global_agents_config().document.agents]
    assert ids == ["legacy-agent", "shared"]


def test_agent_files_join_the_catalog_and_win_clashes(scopes: dict[str, Path]) -> None:
    scopes["legacy"].write_text(LEGACY, encoding="utf-8")
    _agent(scopes["user_agents"], "reviewer-gpt-agent", GPT)
    _agent(scopes["user_agents"], "shared", GPT)
    mapping, clashes = effective_catalog_mapping()
    assert clashes == ["shared"]
    assert set(mapping["agents"]) == {"legacy-agent", "shared", "reviewer-gpt-agent"}
    assert mapping["agents"]["shared"]["execution_profile_id"] == "shared"  # the agent file won
    composition = resolve_agent_composition(scopes["project"], "reviewer-gpt-agent")
    assert composition is not None
    registry = load_gateway_registry_from_agents_catalog()
    snapshot = registry.resolve_snapshot("reviewer-gpt-agent")
    assert snapshot.provider_id == "gpt-auto"
    assert scopes["legacy"].read_text(encoding="utf-8") == LEGACY  # reads never write agents.yaml


def test_agents_yaml_is_optional_once_agent_files_exist(scopes: dict[str, Path]) -> None:
    scopes["legacy"].unlink(missing_ok=True)
    with pytest.raises(AgentsConfigValidationError):
        EffectiveAgentsRepository().read(scopes["project"])
    _agent(scopes["user_agents"], "reviewer-gpt-agent", GPT)
    agents = [agent["agent_id"] for agent in EffectiveAgentsRepository().read(scopes["project"]).document.agents]
    assert agents == ["reviewer-gpt-agent"]


def test_project_scope_agents_are_not_in_the_machine_catalog(scopes: dict[str, Path]) -> None:
    _agent(scopes["project"] / ".audiagentic" / "agents", "project-only", GPT)
    mapping, _ = effective_catalog_mapping()
    assert "project-only" not in mapping["agents"]


def test_doctor_reports_clashes(scopes: dict[str, Path]) -> None:
    from audiagentic.components.agents.configuration.doctor_checks import check_catalog
    from audiagentic.foundation.lifecycle.doctor import DoctorContext

    scopes["legacy"].write_text(LEGACY, encoding="utf-8")
    _agent(scopes["user_agents"], "shared", GPT)
    [result] = check_catalog(DoctorContext(None))
    assert result.status == "warn" and "shared" in result.message
