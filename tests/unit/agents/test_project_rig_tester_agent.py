"""Regression coverage for this repo's own first real Agent Definition.

Every other agents test composes profiles/roles/definitions in a tmp_path
fixture. This is the one test that reads AUDiaGentic's own canonical project
config (`.audiagentic/config/agents.yaml`) to guard the "rig-tester-agent"
entry created to exercise the AS62/AS63 composition path end-to-end for real,
not synthetically. The GatewayClient's actual submit/dispatch mechanics are
already covered generically (with tmp_path fixtures, not this repo's live
 runtime state) by the gateway lifecycle tests -- deliberately not repeated here,
so this test stays read-only and never writes into the real
`.audiagentic/runtime/` directory.
"""
from __future__ import annotations

from audiagentic.components.agents.models.agent_definition_api import (
    get_agent_definition,
    resolve_agent_definition,
)
from audiagentic.components.agents.models.execution_profile_api import (
    get_execution_profile,
)
from audiagentic.components.agents.models.role_api import get_role
from audiagentic.foundation.paths.package import PACKAGE_ROOT

REPO_ROOT = PACKAGE_ROOT.parent.parent


def test_canonical_agents_config_is_only_project_authority() -> None:
    config_root = REPO_ROOT / ".audiagentic" / "config"
    assert (config_root / "agents.yaml").is_file()
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


def test_placeholder_role_exists() -> None:
    role = get_role(REPO_ROOT, "placeholder")
    assert role["instructions"]


def test_rig_tester_agent_definition_exists_and_cross_references_match() -> None:
    definition = get_agent_definition(REPO_ROOT, "rig-tester-agent")
    assert definition["execution_profile_id"] == "rig-tester"
    assert definition["role_ids"] == ["placeholder"]


def test_rig_tester_agent_resolves_end_to_end() -> None:
    """The full composition -- definition + its profile + its role -- resolves
    together, proving the three real files agree with each other, not just
    that each individually parses."""
    resolved = resolve_agent_definition(REPO_ROOT, "rig-tester-agent")
    assert resolved["agent_id"] == "rig-tester-agent"
    assert resolved["execution_profile"]["provider_id"] == "local-openai"
    assert resolved["execution_profile"]["instances"] == ["ag-rig"]
    assert resolved["roles"][0]["role_id"] == "placeholder"
