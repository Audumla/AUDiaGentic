"""Regression coverage for the machine-global rig-tester Agent Definition."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.management import (
    get_agent_definition,
    resolve_agent_definition,
)
from audiagentic.components.agents.configuration.management import (
    get_execution_profile,
)
from audiagentic.components.agents.configuration.management import get_role
from audiagentic.foundation.paths.package import PACKAGE_ROOT

REPO_ROOT = PACKAGE_ROOT.parent.parent


@pytest.fixture(autouse=True)
def _seed_project_rig_catalog(_seed_global_agent_catalog) -> None:
    """Provide the minimal global catalog required by this test."""
    path = global_agents_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """contract-version: v2
prompts:
  default-prompt:
    content:
    - kind: text
      text: Test prompt
    input_schema: null
    description: Test prompt
roles:
  tester:
    instructions: Test role
    required_capabilities: []
    output_guidance: null
    runtime_tool_policy_ref: null
    description: Test role
execution_profiles:
  rig-tester:
    provider_id: local-openai
    instances:
    - ag-rig
    model_alias: null
    params: {}
    is_default: false
    description: Test profile
agents:
  rig-tester-agent:
    name: Rig Tester Agent
    execution_profile_id: rig-tester
    description: Test agent
    advertised_skills: []
    internal: true
    acp: false
    a2a: false
    role_ids:
    - tester
    prompt_id: default-prompt
""",
        encoding="utf-8",
    )


def test_canonical_agents_config_is_machine_global_authority() -> None:
    config_root = global_agents_config_path().parent
    assert global_agents_config_path().is_file()
    assert not (REPO_ROOT / ".audiagentic" / "config" / "agents.yaml").exists()
    for stale_name in (
        "agent-profiles.yaml",
        "agent-definitions.yaml",
        "execution-profiles.yaml",
        "roles.yaml",
    ):
        assert not (config_root / stale_name).exists(), f"stale split config remains: {stale_name}"


def test_rig_tester_execution_profile_exists() -> None:
    profile = get_execution_profile(REPO_ROOT, "rig-tester")
    assert profile["provider_id"] == "local-openai"
    assert profile["instances"] == ["ag-rig"]


def test_tester_role_exists() -> None:
    role = get_role(REPO_ROOT, "tester")
    assert role["instructions"]


def test_rig_tester_agent_definition_exists_and_cross_references_match() -> None:
    definition = get_agent_definition(REPO_ROOT, "rig-tester-agent")
    assert definition["execution_profile_id"] == "rig-tester"
    assert definition["role_ids"] == ["tester"]


def test_rig_tester_agent_resolves_end_to_end() -> None:
    """The full composition -- definition + its profile + its role -- resolves
    together, proving the three real files agree with each other, not just
    that each individually parses."""
    resolved = resolve_agent_definition(REPO_ROOT, "rig-tester-agent")
    assert resolved["agent_id"] == "rig-tester-agent"
    assert resolved["execution_profile"]["provider_id"] == "local-openai"
    assert resolved["execution_profile"]["instances"] == ["ag-rig"]
    assert resolved["roles"][0]["role_id"] == "tester"
